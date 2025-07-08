# AmbientLed

AmbientLed is a custom integration for Home Assistant that allows you to control your AmbientLed lighting devices directly from your smart home dashboard.

## Features

- **Full control of AmbientLed devices**: Turn on/off, change brightness, color, and effects.
- **Real-time updates**: State changes are reflected instantly thanks to WebSocket communication.
- **Secure authentication**: Each user is authenticated with a unique token generated in the AmbientLed system.
- **Easy setup**: Add the integration via the Home Assistant UI (Config Flow) – just enter your token and (optionally) the backend URL.
- **Multiple device support**: Manage all your AmbientLed lights from one place.
- **Open source**: Actively developed and open for contributions.

## How it works

- The integration connects to your AmbientLed backend using a secure WebSocket connection.
- All commands (on/off, brightness, color, effect) are sent in real time.
- Device state is synchronized automatically between Home Assistant and your AmbientLed devices.

## Getting Started

1. **Obtain your AmbientLed token**  
   Log in to your AmbientLed account and copy your unique user token.

2. **Add the integration**

   - Go to Home Assistant → HACS → Integrations → Custom repositories.
   - Add the GitHub repository for AmbientLed.
   - Install the integration and restart Home Assistant if required.

3. **Configure**

   - In Home Assistant, go to Settings → Devices & Services → Add Integration.
   - Search for “AmbientLed”, enter your token (and optionally the backend URL), and finish the setup.

4. **Enjoy!**  
   Your AmbientLed devices will appear as lights in Home Assistant. You can control them from the dashboard, automations, or voice assistants.

## Documentation

For more information, troubleshooting, and advanced configuration, visit:  
[https://ambientled.pl](https://ambientled.pl)

---

**Author:** Marcin Szarmach
**License:** MIT

---

_This integration is not affiliated with Home Assistant. For support, please use the GitHub issues page or contact the author._
