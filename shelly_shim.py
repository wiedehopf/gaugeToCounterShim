#!/usr/bin/env python3

import urllib.request
import json
import traceback
import sys
import time
import os

def log(msg = "no log message provided"):
    if (type(msg) != str):
        msg = str(msg)
    print(msg, file=sys.stderr)

def sleepTruncatedInterval(interval=1.0, offset=0.0):
    now = time.time()
    sleepFor = interval - ((now + interval) % interval) + offset
    sleepFor = sleepFor % interval
    time.sleep(sleepFor)
    #log(f"slept for {sleepFor}, time now {time.time()}")


meterURL = "http://192.168.7.7"
promDir = "/run/shelly_shim"
interval = 1.0
offset = 0.5

if not os.path.exists(promDir):
    os.mkdir(promDir)

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
        if not value:
            log(f"json missing key: {key}")
            continue
        out += f"# TYPE {key} gauge\n"
        out += f"{key} {value}\n"

    for key in counterKeys:
        value = energyCounters[key]
        retValue = energyCounters[key + "_ret"]
        power = data.get(key + "_power")
        if not power:
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



while True:
    sleepTruncatedInterval(interval=interval, offset=offset)

    try:
        with urllib.request.urlopen(f"{meterURL}/rpc/EM.GetStatus?id=0") as response:
            data = json.load(response)

        filePath = f"{promDir}/hr_shim.prom"
        tmpPath = filePath + ".tmp"
        with open(tmpPath, "w") as file:
            file.write(generateProm(data))
        os.rename(tmpPath, filePath)
    except:
        log(traceback.format_exc())
