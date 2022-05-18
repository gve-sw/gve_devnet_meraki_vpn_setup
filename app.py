""" Copyright (c) 2020 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at
           https://developer.cisco.com/docs/licenses
All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied. 
"""

# Import Section
from email import header
from flask import Flask, render_template, request, url_for, redirect
from collections import defaultdict
import datetime, csv, ipaddress
import requests
import json
from dotenv import load_dotenv
from meraki import DashboardAPI
import os
#import merakiAPI
from dnacentersdk import api

# load all environment variables
load_dotenv()


# Global variables
app = Flask(__name__)
selected_org=None
selected_network=None
networks=[]
success = []
error = ""

#Read data from json file
def getJson(filepath):
	with open(filepath, 'r') as f:
		json_content = json.loads(f.read())
		f.close()

	return json_content

#Write data to json file
def writeJson(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f)
    f.close()


##Routes
#Instructions

#Index
@app.route('/', methods=["GET", "POST"])
def index():
    global selected_org, selected_network, networks
    if request.method == "POST":
        selected_org=request.form.get('organizations_select')
        selected_network=request.form.get('network')

        networks = []
        with open('uploaded.csv', 'r') as f:
            reader = csv.reader(f, delimiter=';')
            i = -1
            for l in reader:
                if i>=0:
                    networks += [{
                        'index' : i,
                        'name' : l[0],
                        'vlan51' : l[7],
                        'vlan52' : l[8],
                        'public' : l[9]
                    }]
                i+=1
        return render_template('home.html', hiddenLinks=True, dropdown_content=getJson('orgs.json'), networks=networks, selected_elements={'organization':selected_org, 'network_id':selected_network}, url="https://dashboard.meraki.com")
    else:
        try:
            #Page without error message and defined header links 
            return render_template('home.html', hiddenLinks=True, dropdown_content=get_orgs_and_networks(), networks=networks, selected_elements={'organization':selected_org, 'network_id':selected_network}, success=success, error=error, url="https://dashboard.meraki.com")
        except Exception as e: 
            print(e)  
            #OR the following to show error message 
            return render_template('home.html', error=False, errormessage="Something went wrong.", errorcode=e, hiddenLinks=True)


#Settings
@app.route('/settings', methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        apikey = request.form.get('apikey')
        settings = getJson("settings.json")
        settings['apikey'] = apikey
        writeJson("settings.json", settings)
        return redirect('/')
    return render_template('settings.html', settings=getJson('settings.json'))

# Input CSV
@app.route("/extract-input", methods=["GET","POST"])
def upload_file_function():
    global CSV_UPLOADED

    settings = getJson("settings.json")
    apikey = settings['apikey']
    uploaded_file = request.files
    file_dict = uploaded_file.to_dict()
    the_file = file_dict["file"]
    if not the_file.filename.lower().endswith('.csv'):
        return "Please upload a valid CSV format, or enter the API keys manually"
    with open('uploaded.csv', 'wb') as f:
        f.write(the_file.read())
    
    return "Read CSV file"

# Confirm details
@app.route("/configure", methods=["GET","POST"])
def configure_vlans():
    global networks, success, error

    settings = getJson("settings.json")
    selected_index = int(dict(request.form.lists())['checkbox'][0])
    network_data = networks[selected_index]
    vlan_51_prefix = int(dict(request.form.lists())['vlan51prefix'][selected_index])
    vlan_52_prefix = int(dict(request.form.lists())['vlan52prefix'][selected_index])

    headers = {
        "X-Cisco-Meraki-API-Key" : settings['apikey'],
        "Content-Type" : "application/json",
        "Accept" : "application/json",
    }

    # 1. Create VLANs
    vlan51_payload = {
        'id' : "51",
        "name" : "G4S Combined",
        "subnet" : f"{network_data['vlan51']}/{vlan_51_prefix}",
        "applianceIp" : str(ipaddress.IPv4Address(network_data['vlan51'])+1)
    }
    vlan52_payload = {
        'id' : "52",
        "name" : "G4S Emizon",
        "subnet" : f"{network_data['vlan52']}/{vlan_52_prefix}",
        "applianceIp" : str(ipaddress.IPv4Address(network_data['vlan52'])+1)
    }
    resp51 = requests.post(f"https://api.meraki.com/api/v1/networks/{selected_network}/appliance/vlans", headers=headers, json=vlan51_payload)
    print(resp51.status_code)
    if resp51.status_code == 201:
        success += ["VLAN 51 configured succesfully"]
        resp52 = requests.post(f"https://api.meraki.com/api/v1/networks/{selected_network}/appliance/vlans", headers=headers, json=vlan52_payload)
        if resp52.status_code == 201:
            success += ["VLAN 52 configured succesfully"]
        else:
            error = f"Error in configuring VLAN 52: {resp52.json()}"
    else:
        error = f"Error in configuring VLAN 51: {resp51.json()}"
    

    # 2. Adjust firewall config
    if error == "":
        fw_rules = requests.get(f"https://api.meraki.com/api/v1/networks/{selected_network}/appliance/firewall/l3FirewallRules", headers=headers).json()['rules']
        if len(fw_rules)>=6:
            fw_rules[2]['srcCidr'] = f"{network_data['vlan51']}/{vlan_51_prefix}"
            fw_rules[3]['srcCidr'] = f"{network_data['vlan51']}/{vlan_51_prefix}"
            fw_rules[4]['srcCidr'] = f"{network_data['vlan52']}/{vlan_52_prefix}"
            fw_rules[5]['srcCidr'] = f"{network_data['vlan52']}/{vlan_52_prefix}"
        else:
            fw_rules += [
                {
                    "comment": "To G4S",
                    "policy": "allow",
                    "protocol": "any",
                    "destCidr": "any",
                    "srcCidr": f"{network_data['vlan51']}/{vlan_51_prefix}"
                },{
                    "comment": "Deny VLAN 51 to RFC 1918",
                    "policy": "deny",
                    "protocol": "any",
                    "destCidr": "any",
                    "srcCidr": f"{network_data['vlan51']}/{vlan_51_prefix}"
                },{
                    "comment": "Allow Emizon to DCs",
                    "policy": "allow",
                    "protocol": "any",
                    "destCidr": "any",
                    "srcCidr": f"{network_data['vlan52']}/{vlan_52_prefix}"
                },{
                    "comment": "Deny Emizon to Network",
                    "policy": "deny",
                    "protocol": "any",
                    "destCidr": "any",
                    "srcCidr": f"{network_data['vlan52']}/{vlan_52_prefix}"
                }]
        resp_fw_rules = requests.put(f"https://api.meraki.com/api/v1/networks/{selected_network}/appliance/firewall/l3FirewallRules", headers=headers, json={"rules" : fw_rules})
        if resp_fw_rules.status_code == 200:
            success += ["Firewall rules configured succesfully"]
        else:
            error = f"Error in configuring firewall rules: {resp_fw_rules.json()}"

    # 3. VPN config
    if error == "":
        vpn_settings = requests.get(f"https://api.meraki.com/api/v1/networks/{selected_network}/appliance/vpn/siteToSiteVpn", headers=headers).json()
        vpn_settings['mode'] = 'hub'
        i=0
        if 'subnets' in vpn_settings:
            for subnet in vpn_settings['subnets']:
                if subnet['localSubnet'] == f"{network_data['vlan51']}/{vlan_51_prefix}":
                    vpn_settings['subnets'][i]['useVpn'] = True
                i+=1
        resp_vpn = requests.put(f"https://api.meraki.com/api/v1/networks/{selected_network}/appliance/vpn/siteToSiteVpn", headers=headers, json=vpn_settings)
        if resp_vpn.status_code == 200:
            success += ["Site-to-site VPN configured succesfully"]
        else:
            error = f"Error in configuring Site-to-site VPN: {resp_vpn.json()}"
    
    m = DashboardAPI(settings['apikey'])
    url = m.networks.getNetwork(selected_network)['url']
    return render_template('home.html', hiddenLinks=True, dropdown_content=getJson('orgs.json'), networks=networks, selected_elements={'organization':selected_org, 'network_id':selected_network}, success=success, error=error, url=url)

def get_orgs_and_networks():
    apikey = getJson('settings.json')['apikey']
    m = DashboardAPI(apikey)
    result = []
    for org in m.organizations.getOrganizations():
        org_entry = {
            "orgaid" : org['id'],
            "organame" : org['name'],
            "networks" : []
        }
        for network in m.organizations.getOrganizationNetworks(org['id']):
            org_entry['networks'] += [{
                'networkid' : network['id'],
                'networkname' : network['name']
            }]
        result += [org_entry]
    writeJson('orgs.json', result)
    result = getJson('orgs.json')
    return result

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5151, debug=True)