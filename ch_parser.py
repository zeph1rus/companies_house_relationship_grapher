import re
import time
import sys
import math
import argparse
import requests
from graphviz import Digraph
from pathlib import Path


################################################
# COMPANIES HOUSE Scraper/Grapher
# github.com/zeph1rus 2019,2024
###############################################


def ch_api_delay():
    # utility method so I only have to change the delay timer here.
    time.sleep(0.8)


def get_sub_url_from_full(furl):
    return furl.replace(base_link_url, "")


def get_number_of_pages(perpage, records):
    if records % perpage == 0:
        return int(records / perpage)
    return math.floor(records / perpage) + 1


def get_node_attr_from_level(level):
    if level == 0:
        return 'crimson'
    if level == 1:
        return 'coral'
    if level == 2:
        return 'cornsilk'
    if level == 3:
        return 'whitesmoke'


def get_relationship_from_level(level):
    if level == 0:
        return 'target'
    if level == 1:
        return 'direct relationship'
    if level == 2:
        return 'fellow director'
    if level == 3:
        return 'indirect relationship'


def get_officer_id_from_url(url):
    # pulls id from the url.
    regex = r'.*/officers/(\S+)/appointments'
    cregex = re.compile(regex)
    off_id = cregex.match(url)
    if off_id is None:
        return None
    return off_id.group(1)


def _get_json_from_url_with_per_page(url, api_key, start_items):
    # don't call this method directly, if you need to call the other one.
    print(f"Getting items {start_items} to {start_items + max_records} - {url}")
    try:
        resp = requests.get((url + f"?items_per_page={str(max_records)}&start_index={str(start_items)}"),
                            auth=(api_key, ''))
        if int(resp.status_code) != 200:
            # raise exception if we get anything but OK
            print(f"Server Errors or Rate limiting {resp.status_code}")
            raise SystemError
        out_json = resp.json()
        return out_json
    except Exception as e_could_not_load_page:
        print(f"Error: Could not load and parse json from {url}, {str(e_could_not_load_page)}")
        return None


def get_json_from_url(url, api_key):

    try:
        # get the initial page.
        ret_json = _get_json_from_url_with_per_page(url, api_key, 0)

        # total records are in every request
        total_records = int(ret_json['total_results'])

        # check if holding/service company detection on if it is return the company with no
        # items structure
        if args.detect and (total_records > args.number):
            ret_json['items'] = {}
            return ret_json

        # if there's only going to be one page, don't bother trying to get more
        if total_records < 50:
            return ret_json

        out_json = ret_json

        # we already have 0 -> max_records, so start there.
        record_start = max_records

        # keep requesting records until you are ahead of total (while will break before you request)
        while record_start < total_records:
            # request page
            page_json = _get_json_from_url_with_per_page(url, api_key, record_start)

            # iterate through items array and add to original json - this avoids me refactoring a bit.
            for item in page_json['items']:
                out_json['items'].append(item)

            # increment record count
            record_start += max_records

        # return json with full items array
        return out_json

    except Exception as err_looping_through:
        print(f"Error: Could not load and parse json from {url}, {str(err_looping_through)}")
        return None


def get_officer_pages_from_company(in_json):
    officer_links = []
    for parsed_officer in in_json['items']:
        if parsed_officer is not None:
            officer_links.append(parsed_officer['links']['officer']['appointments'])
    return officer_links


def parse_appointments(in_json, level, officer_id):
    # Calum Macdonald : don't try to parse if there's an error or the officer is empty.
    if in_json is None:
        print(f"Warning: in_json for officer {officer_id} is dead at level {level}")
        return None

    for com in in_json['items']:
        com_obj = {
            'id':     com['appointed_to']['company_number'],
            'name':   com['appointed_to']['company_name'],
            'status': com['appointed_to']['company_status'],
            'level':  level,
            'url':    com['links']['company']
        }
        if not (next((x for x in companies if x['id'] == com_obj['id']), None)):
            # if com_obj not in companies:
            companies.append(com_obj)

        link_obj = {
            'off_id': officer_id,
            'com_id': com_obj['id'],
            'start':  com.get('appointed_on', None),
            'end':    com.get('resigned_on', None),
            'role':   com['officer_role']
        }
        if link_obj not in links:  # link objects shouldn't change so can do straight compare
            links.append(link_obj)

        officer_obj = {
            'id':    officer_id,
            'name':  com['name'],
            'url':   in_json['links']['self'],
            'level': (level - 1)
        }
        if not (next((x for x in officers if x['id'] == officer_obj['id']), None)):
            officers.append(officer_obj)


##################################
# Constants and initial globals  #
##################################

# Vars
officers = []
companies = []
links = []
base_officer_name = ""
OUTDIR = "output"

# *Constants*
# there is no point setting this higher than this value as it is ignored.
max_records = 50
base_url = 'https://api.company-information.service.gov.uk'
base_link_url = 'https://find-and-update.company-information.service.gov.uk'

if __name__ == "__main__":

    # Parse Command Line Arguments
    cArgs = argparse.ArgumentParser(description='Scrape and Graph Companies House Relationships')
    cArgs.add_argument('-u', '--url', required=True,
                       help='officer url  (e.g.https://find-and-update.company-information.service.gov.uk/officers/{id}/appointments)')
    cArgs.add_argument('-k', '--apikey', required=True, help='Companies House Api Key')
    cArgs.add_argument('-d', '--detect', required=False, default=False, type=bool,
                       help='Attempt to detect and remove holding or service companies (true/false - default false)')
    cArgs.add_argument('-n', '--number', required=False, type=int, default=250,
                       help='Number of appointments over which the firm is considered a service company (requires -d, default 250)')
    args = cArgs.parse_args()

    print("\n\nCOMPANIES HOUSE RELATIONSHIP GRAPH\n\n")
    # Set up initial request
    base_auth = args.apikey
    base_officer = get_sub_url_from_full(args.url)

    if args.detect:
        print(f"Service Company Detection On - Threshold: {str(args.number)}")
    print(f"Officer ID for scraping: {get_officer_id_from_url(base_officer)}\nStarting Scraping:")

    # Perform Initial Request
    try:
        json_from_ch = get_json_from_url((base_url + base_officer), base_auth)
    except Exception as could_not_get_initial_json:
        print(f"EXIT: Couldn't get companies house data: {str(could_not_get_initial_json)}")
        sys.exit(-1)

    # Append initial officer to the officers list
    officers.append({
        'id':    get_officer_id_from_url(base_officer),
        'name':  json_from_ch['name'],
        'url':   json_from_ch['links']['self'],
        'level': 0
    })

    # Create file names for output
    base_officer_name = json_from_ch['name']

    # create an output directory if it doesn't exist
    try:
        Path(OUTDIR).mkdir(parents=False, exist_ok=True)
    except IOError as e_create_dir:
        print(f"Error Creating Image Directory: {e_create_dir}")
        exit(1)

    base_filename = (f"{OUTDIR}/" + "".join([c for c in base_officer_name if c.isalpha() or c.isdigit()]).rstrip())

    # Try Parsing the first page
    try:
        parse_appointments(json_from_ch, 1, get_officer_id_from_url(base_officer))
    except Exception as initial_parse_except:
        print(f"EXIT: Couldn't parse initial json {str(initial_parse_except)}")
        sys.exit(-1)

    # if there are actually any appointments
    if len(json_from_ch['items']) > 0:
        # Iterate through the companies on the appointment page.
        for company_obj in json_from_ch['items']:

            # grab url for the company
            company_link = company_obj['links']['company']

            # pull officer data from the companies api using the previously got url.
            company_page = get_json_from_url((base_url + company_link + '/officers'), base_auth)

            # iterate over
            u_links = get_officer_pages_from_company(company_page)

            # iterate over officer appointmennts
            for link in u_links:
                if isinstance(link, str):
                    try:
                        appointments_page = get_json_from_url((base_url + link), base_auth)
                        parse_appointments(appointments_page, 3, get_officer_id_from_url(link))
                    except Exception as parse_appointments_ml_ex:
                        print(
                            f"Error: Parsing appts in main route failure - ignoring but consider this run junk - {str(parse_appointments_ml_ex)}")
                        pass
                ch_api_delay()
            ch_api_delay()

    print(f"Companies: {len(companies)}")
    print(f"Officers: {len(officers)}")
    print(f"Links: {len(links)}")

    # Construct graph in dot language.
    dot = Digraph(comment='Graph')

    # creating in csv allows a clickable image - each node takes you to the ch page.
    dot.format = 'svg'
    dot.engine = 'sfdp'
    dot.attr('graph', overlap='false')
    dot.attr('graph', concentrate='true')
    dot.attr('graph', splines='true')
    dot.attr('node', shape='invhouse')

    for company in companies:
        dot.attr('node', style='filled', fillcolor=get_node_attr_from_level(company['level']),
                 href=(base_link_url + company['url']))
        dot.node(company['id'], label=f"{company['name']}\n{company['status']}")
    dot.attr('node', shape='box')

    for officer in officers:
        dot.attr('node', style='filled', fillcolor=get_node_attr_from_level(officer['level']),
                 href=(base_link_url + officer['url']))
        dot.node(officer['id'], label=f"{officer['name']}")

    for link in links:
        dot.edge(link['off_id'], link['com_id'])

    # Render the graph
    # When I wrote most of this I wasn't using an Apple Silicon machine
    # it doesn't take long to render any more!
    print("Rendering Graph!\nThis WILL take some time")

    # here is the work.
    graph_fname = dot.render(base_filename + '.gv')
    print(f"Rendered Graph - Filename: {graph_fname}")

    # write CSV to file. Not using csvwriter as it's probably more code to worry about than otherwise.  If this gets more complex
    # swap to a csv dict writer.
    print(f"Writing CSV\nOutput Filename: {base_filename + '.csv'}")
    with open((base_filename + '.csv'), 'w', newline=None, encoding="utf-8") as outcsv:
        try:
            outcsv.write("Type,Name,Relationship to Target,Link\n")
            for company in companies:
                outcsv.write(
                    f"\"company\",\"{company['name']}\",\"{get_relationship_from_level(company['level'])}\",{(base_link_url + company['url'])}\n")
            for officer in officers:
                outcsv.write(
                    f"\"officer\",\"{officer['name']}\",\"{get_relationship_from_level(officer['level'])}\",{(base_link_url + officer['url'])}\n")
        except Exception as wcsvex:
            print(f"Failed Writing CSV: {str(wcsvex)}")
