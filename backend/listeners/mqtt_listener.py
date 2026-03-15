"""
MQTT Listener — Module 1

Subscribes to a topic on an MQTT broker.
Useful when devices publish alerts to an MQTT bus instead of HTTP.

Enable with MQTT_ENABLED=true in .env.
Set MQTT_BROKER, MQTT_PORT, MQTT_TOPIC as needed.
"""
import asyncio
import json
import logging

from backend.config import get_settings

logger = logging.getLogger("amfi.listener.mqtt")
settings = get_settings()


class MQTTListener:
    def __init__(self, on_message_callback):
        self.callback = on_message_callback

    async def start(self):
        if not settings.mqtt_enabled:
            logger.info("MQTT listener disabled (set MQTT_ENABLED=true to enable)")
            return

        try:
            import asyncio_mqtt as aio_mqtt

            async with aio_mqtt.Client(
                hostname=settings.mqtt_broker,
                port=settings.mqtt_port,
            ) as client:
                logger.info(
                    "MQTT listener connected to %s:%d, subscribing to '%s'",
                    settings.mqtt_broker, settings.mqtt_port, settings.mqtt_topic,
                )
                await client.subscribe(settings.mqtt_topic)
                async for message in client.messages:
                    topic = str(message.topic)
                    try:
                        payload = json.loads(message.payload.decode())
                    except Exception:
                        payload = {"raw": message.payload.decode()}
                    logger.info("MQTT message on topic %s", topic)
                    await self.callback(topic, payload)

        except ImportError:
            logger.warning("asyncio-mqtt not installed — MQTT listener disabled")
        except Exception as e:
            logger.error("MQTT listener error: %s", e)
