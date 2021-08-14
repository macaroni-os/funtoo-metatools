#!/bin/sh

ARGS=()

while [ "$#" -gt 0 ]; do
	key="$1"

	case "$key" in
		--logfile)
			LOGFILE="$2"
			shift 2
			;;
		*)
			ARGS+=("$1")
			shift
			;;
	esac
done

merge-kits "${ARGS[@]}" 2>&1 | tee "${LOGFILE:-output-$(date +%F_%T).log}"
