import asyncio

from livekit import api
from livekit.protocol.sip import CreateSIPOutboundTrunkRequest, SIPOutboundTrunkInfo

async def main():
  livekit_api = api.LiveKitAPI()

  trunk = SIPOutboundTrunkInfo(
    name = "My trunk",
    address = "2969858100306124.ap-southeast-1.zt.plivo.com",
    numbers = ['+918035736839'],
    auth_username = "garvit",
    auth_password = "test123@"
  )

  request = CreateSIPOutboundTrunkRequest(
    trunk = trunk
  )

  trunk = await livekit_api.sip.create_sip_outbound_trunk(request)

  print(f"Successfully created {trunk}")

  await livekit_api.aclose()

asyncio.run(main())