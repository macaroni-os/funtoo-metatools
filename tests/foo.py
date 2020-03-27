#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import asyncio
import os
import signal
from asyncio.subprocess import STDOUT
from tornado.websocket import websocket_connect
from tornado.escape import json_encode
from pymongo import MongoClient
import logging
from json import loads

def db_initialize(corp_member=False):
	print("Initializing database")
	illdrive = MongoClient(serverSelectionTimeoutMS=1000).illdrive
	illdrive.cities.delete_many({})
	illdrive.users.delete_many({})
	illdrive.invoices.delete_many({})
	abq = {
		"name": "abq",
		"fullname": "Albuquerque",
		"state": "NM",
		"distance": {
			# 56 km = ~ 35 miles
			"maximum" : 56 * 1000
		},
		"geoloc": { "type": "Point", "coordinates" : [ -106.6504, 35.0844 ] }
	}

	abq_id = illdrive.cities.insert_one(abq).inserted_id
	member = {
		"name" : "member",
		"desc" : "regular membership for individual I'll Drive users.",
		"rate" : 1500
	}

	member_id = illdrive.plans.insert_one(member).inserted_id

	if corp_member is True:
		corp_member = {
			"name" : "funtoo",
			"desc" : "Funtoo Solutions, Inc.",
			"rate" : 5000,
			"max_users" : 10,
			"corporate" : True,
			"users" : [ { "email" : "drobbins@funtoo.org"} ]
		}
		member_id = illdrive.plans.insert_one(corp_member).inserted_id
	return illdrive

process = None

def teardown_function():
	logging.warning("RUNNING TEARDOWN")
	global process
	try:
		process.kill()
	except ProcessLookupError:
		pass

	async def cleanup():
		tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
		[task.cancel() for task in tasks]
	asyncio.get_event_loop().run_until_complete(cleanup())

class ServerError(Exception):
	pass

async def _read_stream(stream, cb):
	while True:
		line = await stream.readline()
		if line:
			cb(line)
		else:
			break

def logging_output(line_in_bytes):
	logging.warning(line_in_bytes.decode("utf-8").rstrip("\n"))


async def _stream_subprocess(cmd, stdout_cb, stderr_cb):
	global process
	process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
	await asyncio.wait([
		_read_stream(process.stdout, stdout_cb),
		_read_stream(process.stderr, stderr_cb)
	])
	return await process.wait()

async def run_server():
	logging.warning("STARTING SERVER")
	await _stream_subprocess(
		[ "/usr/bin/python3", "/home/drobbins/development/x-ldap/bin/illdrive-server"],
		logging_output,
		logging_output
	)

async def runner(msg_pairs, env):
	global process
	db_initialize(corp_member=True)
	asyncio.create_task(run_server())
	await asyncio.sleep(1)
	ws = await websocket_connect("ws://127.0.0.1:9000/ws/1.0/connect")
	msg_pos = 0
	while msg_pos < len(msg_pairs):
		out_msg = msg_pairs[msg_pos]["req"]
		if callable(out_msg):
			send_out = json_encode(out_msg(env))
		else:
			send_out = json_encode(out_msg)
		logging.warning("SENDING: " + send_out)
		if "prewait" in msg_pairs[msg_pos]:
			logging.warning("SLEEPING FOR %s SECONDS" % msg_pairs[msg_pos]["prewait"])
			await asyncio.sleep(msg_pairs[msg_pos]["prewait"])
		await ws.write_message(send_out)
		if "resp" in msg_pairs[msg_pos]:
			try:
				msg_resp = await asyncio.wait_for(ws.read_message(), timeout=5)
				logging.warning("RECEIVED: " + msg_resp)
				msg_pairs[msg_pos]["resp"](loads(msg_resp), env)
			except asyncio.TimeoutError as e:
				raise e
			msg_pos += 1
	try:
		process.kill()
	except ProcessLookupError:
		pass
	tasks = [t for t in asyncio.all_tasks() if t is not
			 asyncio.current_task()]
	[task.cancel() for task in tasks]

def harness(msg_pairs, env):
	os.setpgrp()
	asyncio.get_event_loop().run_until_complete(runner(msg_pairs, env))


def test_hello(bad_card=False):

	env = {
		"device_key" : None,
		"user_document" : None,
		"activation_key" : None
	}

	def msg1_verify(incoming, env):
		assert incoming == { "action" : "start-signup" }

	def msg2_verify(incoming, env):
		assert "action" in incoming and incoming["action"] == "start-verify"
		assert "json_dict" in incoming
		assert "user_document" in incoming["json_dict"]
		env["user_document"] = incoming["json_dict"]["user_document"]
		assert "device_key" in incoming["json_dict"]
		env["device_key"] = incoming["json_dict"]["device_key"]
		assert env["device_key"] == env["user_document"]["devices"][0]["key"]
		assert "activation_key" in env["user_document"]["devices"][0]
		env["activation_key"] = env["user_document"]["devices"][0]["activation_key"]

	def msg3_in(env):
		return {
			"action": "verify",
			"msg_type": "req",
			"device_key": env["device_key"],
			"json_dict": {
				"verification_code": env["activation_key"],
			}
		}

	def msg3_verify(incoming, env):
		assert "action" in incoming and incoming["action"] == "verify"
		assert "status" in incoming["json_dict"] and incoming["json_dict"]["status"] == "success"
		assert "user_document" in incoming["json_dict"]
		user = env["user_document"] = incoming["json_dict"]["user_document"]
		assert env["device_key"] == user["devices"][0]["key"]
		assert "user" in user["roles"]
		assert "member" not in user["roles"] # ensure corp membership does not apply
		assert user["devices"][0]["status"] == "reg"
		assert "plan" in user
		assert "name" in user["plan"] and user["plan"]["name"] == "member"
		assert user["plan"]["rate"] == 1500

	def msg4_in(env):
		return {
			"action": "subscribe",
			"msg_type": "req",
			"device_key": env["device_key"],
			"json_dict": {
				"card_nonce": "cnon:card-nonce-ok",
				"card_zip": "94103",
			},
		}

	def msg4_in_bad(env):
		return {
			"action": "subscribe",
			"msg_type": "req",
			"device_key": env["device_key"],
			"json_dict": {
				"card_nonce": "fart",
				"card_zip": "90210",
			},
		}

	def msg4_verify(incoming, env):
		env["user_document"] = incoming["json_dict"]["user_document"]
		assert "action" in incoming and incoming["action"] == "subscribe"
		assert "status" in incoming["json_dict"] and incoming["json_dict"]["status"] == "success"
		u = env["user_document"]
		assert u["payment-info"]["payment-method"] == "square"
		assert "member" in u["roles"]
		assert "subscription" in u
		assert "status" in u["subscription"] and u["subscription"]["status"] == "active"
		assert "card_nonce" not in u["payment-info"]["cards"][0]

	def msg4_verify_bad(incoming, env):
		env["user_document"] = incoming["json_dict"]["user_document"]
		assert "action" in incoming and incoming["action"] == "subscribe"
		assert "status" in incoming["json_dict"] and incoming["json_dict"]["status"] == "failure"
		u = env["user_document"]
		assert u["payment-info"]["payment-method"] == "square"
		assert "member" not in u["roles"]
		assert "subscription" not in u or "status" not in u["subscription"]

	def msg5_in(env):
		return {
			"action": "geoloc",
			"msg_type": "req",
			"device_key": env["device_key"],
			"json_dict": {
				"location": { 'type' : 'Point', 'coordinates' : [ -106.6504, 35.0844 ] },
			},
		}

	def msg5_verify(incoming, env):
		env["user_document"] = incoming["json_dict"]["user_document"]
		assert "action" in incoming and incoming["action"] == "geoloc"
		assert "status" in incoming["json_dict"] and incoming["json_dict"]["status"] == "success"
		user = env["user_document"]
		assert env["device_key"] == user["devices"][0]["key"]
		assert "geoloc" in user["devices"][0]
		assert user["devices"][0]["city"]["name"] == "abq"


	msg_pairs = [
		{
			"req": {
				"action": "hello",
				"msg_type": "req",
				"device_key": None
			},
			"resp": msg1_verify
		},
		{
			"req": {
				"action": "signup",
				"msg_type": "req",
				"device_key": None,
				"json_dict": {
					"phone": "TEST:5054147209",
					"fullname": "Daniel Robbins",
					"email": "bobbins@funtoo.org"
				}
			},
			"resp": msg2_verify
		},
		{
			"req": msg3_in,
			"resp": msg3_verify
		},
	]
	if bad_card is True:
		msg_pairs.append({

			"req": msg4_in_bad,
			"resp": msg4_verify_bad
		})
	else:
		msg_pairs.append({
			"req": msg4_in,
			"resp": msg4_verify
		})

	msg_pairs.append({
		"req": msg5_in,
		"resp": msg5_verify
	})
	harness(msg_pairs, env)
	
	assert env["device_key"] != None
	assert env["user_document"] != None
	assert env["activation_key"] != None

def test_hello_bad():
	test_hello(bad_card=True)

# add code to create db state and then send messages and look at responses.

#server sends:
{ "action" : "start-verify" }
{ "aciton" : "start-signup" }

#
# { "action" : "hello", "msg_type" : "req", "device_key" : device_key }
# { "action" : "signup", "msg_type" : "req", "device_key" : device_key, json_dict: { "phone" "fullname" "email" } }
# { "action" : "verify" "msg_type" : "req", "device_key" : device_key, json_dict : { "verification_code" : key }}


# vim: ts=4 sw=4 noet
