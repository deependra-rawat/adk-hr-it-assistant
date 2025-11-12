import traceback
import requests
from zeep import Client
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin
import os

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"D:\Projects\Godrej\GODREJ-BOT-main\service_account_key.json"

REMEDY_WSDL_URL = "https://godrejservicehub-qa.onbmc.com/arsys/WSDL/public/onbmc-s/GIL_HPD_Incident_Create_WS"
REMEDY_USERNAME = "voice.ai"
REMEDY_PASSWORD = "voiceai"


def create_remedy_incident(
    Issue: str,
    Service: str,
    SupportTeam: str,
    UserEmailBody: str,
    Subject: str
):
    try:
        session = requests.Session()
        history = HistoryPlugin()
        transport = Transport(session=session)
        client = Client(wsdl=REMEDY_WSDL_URL, transport=transport, plugins=[history])
        auth_element = client.get_element('ns0:AuthenticationInfo')
        auth_header = auth_element(userName=REMEDY_USERNAME, password=REMEDY_PASSWORD)

        incidentId = client.service.Create_Incident(
            Customer_Company="GIL - Corporate",
            First_Name="Anshuman",
            Last_Name="chandel",
            Middle_Initial="",
            Login_ID="anshuman.chandel",
            Service_Type="User Service Request",
            Status="Assigned",
            Impact=4000,
            Urgency=4000,
            Description=Subject,
            Detailed_Decription=UserEmailBody,
            Reported_Source="Chatbot",
            Location_Company="GIL - Corporate",
            Categorization_Tier_1="End Users Services",
            Categorization_Tier_2=Service,
            Categorization_Tier_3=Issue,
            z1D_Action="CREATE",
            RequestedBy_Company="GIL - Corporate",
            RequestedBy_FirstName="Voice",
            RequestedBy_LastName="AI",
            _soapheaders=[auth_header]
        )

        return {"incident_id": incidentId}
    except Exception as e:
        return {"error": str(e), "details": traceback.format_exc()}
