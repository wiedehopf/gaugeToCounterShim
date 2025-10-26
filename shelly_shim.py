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

def sleepTruncatedInterval(interval=1.0):
    now = time.time()
    sleepFor = interval - ((now + interval) % interval)
    time.sleep(sleepFor)
    #log(f"slept for {sleepFor}, time now {time.time()}")


meterURL = "http://192.168.7.7"
promDir = "/run/shelly"
interval = 1.0

if not os.path.exists(promDir):
    os.mkdir(promDir)

# counters in Watt seconds
energyCounters = {
        "a_act": 0.0,
        "b_act": 0.0,
        "c_act": 0.0,
        "a_aprt": 0.0,
        "b_aprt": 0.0,
        "c_aprt": 0.0,
        "total_act": 0.0,
        "total_aprt": 0.0
        }

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
    global energyCounters
    global otherGauges
    global interval
    out = ""
    for key in otherGauges:
        value = data.get(key)
        if not value:
            log(f"json missing key: {key}")
            continue
        out += f"{key} {value}\n"

    for key, value in energyCounters.items():
        power = data.get(key + "_power")
        if not power:
            log(f"json missing key: {key}")
            continue
        value += float(power) * interval
        energyCounters[key] = value
        out += f"{key}_watt_seconds {value}\n"

    return out



while True:
    sleepTruncatedInterval(interval=interval)

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
