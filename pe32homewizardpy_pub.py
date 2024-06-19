#!/usr/bin/env python3
"""
FIXME: docs

This is compatible with the water-version of pe32proxsenspy_pub.

https://api-documentation.homewizard.com/docs/endpoints/api-v1-data/#watermeter-hwe-wtr
"""
import asyncio
import sys
from json import loads
from os import environ
from time import time

from asyncio_mqtt import Client as MqttClient

__version__ = 'pe32homewizardpy_pub-FIXME'

# log = getLogger()  # FIXME


def millis():
    return int(time() * 1000)


APP_START_TM = millis()


class Pe32HomeWizardPublisher:
    def __init__(self, prefix):
        assert prefix == 'w_', prefix
        self._prefix = prefix  # 'w_' (water) or 'g_' (gas)

        self._mqtt_broker = environ.get(
            'PE32HOMEWIZARD_BROKER', 'test.mosquitto.org')
        self._mqtt_topic = environ.get(
            'PE32HOMEWIZARD_TOPIC', 'myhome/infra/water/xwwwform')
        self._mqttc = None
        self._guid = environ.get(
            'PE32HOMEWIZARD_GUID', 'EUI48:11:22:33:44:55:66')

        # Set this instead of 'total_liter_offset_m3'.
        self._offset_liter = int(environ.get(
            'PE32HOMEWIZARD_OFFSETLITER', '0'))

    def open(self):
        # Unfortunately this does use a thread for keepalives. Oh well.
        # As long as it's implemented correctly, I guess we can live
        # with it.
        self._mqttc = MqttClient(self._mqtt_broker)
        return self._mqttc

    async def publish(self, relative, flow):
        # log.info(f'publish: {absolute} {relative} {flow}')
        absolute = relative + self._offset_liter

        tm = millis() - APP_START_TM
        mqtt_string = (
            f'device_id={self._guid}&'
            f'{self._prefix}absolute_l={absolute}&'
            f'{self._prefix}relative_l={relative}&'
            f'{self._prefix}flow_mlps={flow}&'
            f'dbg_uptime={tm}&'
            f'dbg_version={__version__}')

        try:
            await self._mqttc.publish(
                self._mqtt_topic, payload=mqtt_string.encode('ascii'))
        except Exception as e:
            # log.error(f'Got error during publish of {mqtt_string}: {e}')
            print(f'Got error during publish of {mqtt_string}: {e}')
            exit(1)

        # log.debug(f'Published: {mqtt_string.replace("&", " ")}')
        print(f'Published: {mqtt_string.replace("&", " ")}')


async def oneshot(host, port):
    # Yes, doing HTTP client myself instead of finding a dependency for asyncio
    # was faster. Not nice maybe, but it works.
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(
        b'GET /api/v1/data HTTP/1.0\r\nConnection: close\r\n\r\n')

    data = bytearray()
    while True:
        extra = await reader.read(8192)
        if extra == b'':
            raise ValueError(data)

        data += extra
        headers = data.split(b'\r\n')
        content_length_header = [
            i for i in headers[0:-1]  # skip last, we must have a CRLF after..
            if i.lower().startswith(b'content-length:')]

        if content_length_header:
            content_length = int(
                content_length_header[0].split(b':', 1)[1].strip())

            if b'\r\n\r\n' in data:
                headers, body = data.split(b'\r\n\r\n', 1)
                if len(body) >= content_length:
                    break

    writer.close()  # synchronous

    body = body.decode('utf-8')
    data = loads(body)
    assert data['total_liter_offset_m3'] == 0, data
    # {'wifi_ssid': 'PrettyFlyForA', 'wifi_strength': 100,
    #  'total_liter_m3': 0.018, 'active_liter_lpm': 0,
    #  'total_liter_offset_m3': 0}
    return data


async def mainloop(host, port):
    publisher = Pe32HomeWizardPublisher('w_')

    PUBLISH_EVERY = 300e3  # 5 minutes
    last_relative = last_flow = None
    last_pub = APP_START_TM - PUBLISH_EVERY

    async with publisher.open():
        while True:
            try:
                data = await asyncio.wait_for(
                    oneshot(host, port), timeout=5)

                relative = int(data['total_liter_m3'] * 1000)
                flow = int(data['active_liter_lpm'] * 1000.0 / 60.0)

                if relative != last_relative or flow != last_flow or (
                        (millis() - last_pub) >= PUBLISH_EVERY):
                    last_relative = relative
                    last_flow = flow
                    last_pub = millis()

                    await asyncio.wait_for(
                        publisher.publish(relative, flow),
                        timeout=5)

            except asyncio.TimeoutError:
                print('timeout, alas..')
            else:
                await asyncio.sleep(1)


def main():
    # Output
    if sys.argv[1:2] == ['--publish']:
        sys.stdout.reconfigure(line_buffering=True)  # PYTHONUNBUFFERED
        host, port = sys.argv[2:]  # port defaults to 80
        asyncio.run(mainloop(host, port))
    else:
        host, port = sys.argv[1:]  # port defaults to 80
        kv = asyncio.run(oneshot(host, port))
        for key, value in kv.items():
            print('{:16}  {}'.format(key, value))


if __name__ == '__main__':
    main()
