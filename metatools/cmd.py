import asyncio


async def capture_bg(cmd):
	"""
	Run command in a forked background process, await its completion -- don't emit any output, but instead capture
	stdout and err into a combined string.

	Return the process object and the combined string of stdout and stderr.
	"""
	proc = await asyncio.create_subprocess_shell(cmd,
	stdout=asyncio.subprocess.PIPE,
	stderr=asyncio.subprocess.STDOUT)

	stdout, stderr = await proc.communicate()
	return proc, stdout.decode("utf-8")


async def run_bg(cmd, env=None):
	"""
	Run command in a forked background process, await its completion -- output all its output to existing stdout/err.
	Return its returncode.
	"""
	proc = await asyncio.create_subprocess_shell(cmd, env=env)
	return await proc.wait()


class ShellError(Exception):
	pass


async def run_shell(cmd_list, abort_on_failure=True, chdir=None, logger=None):
	if isinstance(cmd_list, list):
		cmd_str = " ".join(cmd_list)
	else:
		cmd_str = cmd_list
	if logger:
		logger.info(f"executing: {cmd_str}")
	if chdir:
		cmd_str = f"( cd {chdir}; {cmd_str})"

	proc, output = await capture_bg(cmd_str)

	if proc.returncode != 0:
		if abort_on_failure:
			raise ShellError(f"Aborted due to failed command. Error executing '{cmd_str}':\n{output}\n")
		else:
			return False
	return True
