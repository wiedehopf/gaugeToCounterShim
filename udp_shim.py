#!/usr/bin/env python3

import json
import traceback
import sys
import time
import os
import threading
import socket

def log(msg = "no log message provided"):
    if (type(msg) != str):
        msg = str(msg)
    msg = msg.strip()
    print(msg, file=sys.stderr)

def logExceptionOnly(ex):
    lines = traceback.format_exception_only(ex)
    log(lines[0])

def sleepTruncatedInterval(interval=1.0, offset=0.0):
    now = time.time()
    sleepFor = interval - ((now + interval) % interval) + offset
    sleepFor = sleepFor % interval
    time.sleep(sleepFor)

    #if sleepFor > 1 or sleepFor < 0.8:
    #    log(f"slept for {sleepFor}, time now {time.time()}")


meterIp = "192.168.7.7"
meterPort = 1010
promDir = "/run/shelly_shim"
interval = 1.0

if not os.path.exists(promDir):
    os.mkdir(promDir)

client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

counterKeys = [
        "a_act",
        "b_act",
        "c_act",
        "total_act",
        "a_aprt",
        "b_aprt",
        "c_aprt",
        "total_aprt"
        ]

# counters in Watt seconds
energyCounters = {}

for key in counterKeys:
    energyCounters[key] = 0.0
    energyCounters[key + "_ret"] = 0.0

otherGauges = [
        "a_voltage",
        "b_voltage",
        "c_voltage",
        "a_freq",
        "b_freq",
        "c_freq",
        "a_pf",
        "b_pf",
        "c_pf"
        ]

def generateProm(data):
    global counterKeys
    global energyCounters
    global otherGauges
    global interval
    out = ""
    for key in otherGauges:
        value = data.get(key)
        if value == None:
            log(f"json missing key: {key}")
            continue
        out += f"# TYPE {key} gauge\n"
        out += f"{key} {value}\n"

    for key in counterKeys:
        value = energyCounters[key]
        retValue = energyCounters[key + "_ret"]
        power = data.get(key + "_power")
        if power == None:
            log(f"json missing key: {key}")
            continue

        # emit active power as it is as well
        if "act" in key:
            out += f"# TYPE {key}_power gauge\n"
            out += f"{key}_power {power}\n"

        power = float(power)
        if power > 0.0:
            value += float(power) * interval
        else:
            retValue -= float(power) * interval

        energyCounters[key] = value
        energyCounters[key + "_ret"] = retValue

        promKey = f"{key}_watt_seconds"
        out += f"# TYPE {promKey} counter\n"
        out += f"{promKey} {round(value, 1)}\n"

        # for the apparent power we don't need this, it never shows negative on this meter
        if not "aprt" in key:
            promKey = f"{key}_ret_watt_seconds"
            out += f"# TYPE {promKey} counter\n"
            out += f"{promKey} {round(retValue, 1)}\n"

    return out

def pruneResults(results):
    cutoff = time.time() - 6.5
    for ts in list(results.keys()):
        if ts < cutoff:
            del results[ts]

offset = 0.05
attempts = 4
cushion = 0.1
timeout = (interval - offset - cushion) / attempts
#log(timeout)

lastResults = dict()

elapsed = 0
lastUpdate = round(time.time(), 3)
while True:
    sleepTruncatedInterval(interval=interval, offset=offset)

    for attempt in range(attempts):
        try:
            client.settimeout(timeout)

            msg = b'{"id":0,"method":"EM.GetStatus","params":{"id":0}}\n'
            client.sendto(msg, (meterIp, meterPort))

            start = round(time.time(), 3)

            raw, server = client.recvfrom(1024)
            result = json.loads(raw).get('result')
            if not result:
                continue

            now = round(time.time(), 3)
            elapsed = round(now - start, 3)

            if elapsed > timeout + 0.1:
                log(f"elapsed: {elapsed}")

            pruneResults(lastResults)

            lastResults[now] = result

            filePath = f"{promDir}/lastResults.json"
            tmpPath = filePath + ".tmp"
            with open(tmpPath, "w") as file:
                json.dump(lastResults, file, indent=2)
            os.rename(tmpPath, filePath)

            filePath = f"{promDir}/hr_shim.prom"
            tmpPath = filePath + ".tmp"
            with open(tmpPath, "w") as file:
                file.write(generateProm(result))
            os.rename(tmpPath, filePath)
            now = round(time.time(), 3)
            elapsed = round(now - lastUpdate, 3)
            if elapsed > 1.5:
                log(f"elapsed: {elapsed} lastUpdate: {lastUpdate} thisUpdate: {now}")
            lastUpdate = now
            break

        except TimeoutError as ex:
            logExceptionOnly(ex)
            if attempt == attempts - 1:
                now = round(time.time(), 3)
                log(f"WARNING: no data between {lastUpdate} {now}")

