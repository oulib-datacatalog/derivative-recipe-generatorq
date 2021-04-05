import yaml
import logging
import re
from lxml import etree as ET
from operator import is_not
from functools import partial
from string import whitespace
import requests
from collections import OrderedDict
import os
import boto3
from botocore.exceptions import ClientError
from .configs import base_url, alma_api_url, repository_url, bag_gateway_url, error_bags_url
from .configs import digital_objects_url
from json import dumps

def _get_mmsid_bag_name(bag):
    """ parse mmsid from end of bag name """
    mmsid = bag.split("_")[-1].strip()  # using bag name formatting: 1990_somebag_0987654321
    if re.match("^[0-9]{8,19}$", mmsid):  # check that we have an mmsid like value
        return mmsid
    return None

def _get_mmsid_catalog(bag):
    """ fetch mmsid from data catalog metadata """
    catalog = searchcatalog(bag)
    return catalog.get("mmsid")

def searchcatalog(bag):
    query = {"filter": {"bag": bag}}
    search_url = f"{digital_objects_url}?format=json&query={dumps(query)}"
    resp = requests.get(search_url)
    catalogitems = resp.json()
    if catalogitems['count']:
        return catalogitems['results'][0]

def _get_mmsid_bag_info(bag):
    s3 = boto3.resource('s3')

    #FIXME: Change this bucket-name
    bucket_name = "ul-cc"
    print("Bucket Name in get_mmsid - {0}".format(bucket_name))
    s3_key = "{0}/{1}/{2}".format('source', bag, 'bag-info.txt')
    try:
        recipe_obj = s3.Object(bucket_name, s3_key)
    except ClientError as e:
        logging.error(e)
    # recipe_obj = s3.Object(bucket_name, s3_key)
    bag_info = yaml.load(recipe_obj.get()['Body'].read())
    try:
        mmsid = bag_info['FIELD_EXTERNAL_DESCRIPTION'].split()[-1].strip()
        print("bagname --- {0} = mmsid = {1}".format(bag, mmsid))
    except KeyError:
        logging.error("Cannot determine mmsid for bag from bag-info: {0}".format(bag))
        return None
    if re.match("^[0-9]{8,19}$", mmsid):  # check that we have an mmsid like value
        print("The matched value is=", re.match("^[0-9]{8,19}$", mmsid))
        return mmsid
    return None

def _get_mmsid_marc_recipe(bag):
    """ parse mmsid from marc xml linked in recipe file """
    recipe_url = guess_recipe_url(bag)
    resp_json = requests.get(recipe_url).json()
    marc_url = resp_json['recipe']['metadata']['marcxml']
    resp = requests.get(marc_url).content
    tree = ET.fromstring(resp)
    found_elements = tree.xpath(
        '//ns:record/ns:controlfield[@tag=001]',
        namespaces={"ns": "http://www.loc.gov/MARC21/slim"}
    )
    for element in found_elements:
        mmsid = element.text
        if re.match("^[0-9]{8,19}$", mmsid):
            return mmsid
    return None

def guess_recipe_url(bag):
    """ generate recipe url based on hard coded derivative path """
    return f"{bag_gateway_url}/derivative/{bag}/jpeg_040_antialias/{bag.lower()}.json"

def get_mmsid(bag_name):
    """

    :param bag_name: name of the bag
    :return: mmsid or None
    """

    for func in [_get_mmsid_bag_name, _get_mmsid_catalog, _get_mmsid_bag_info, _get_mmsid_marc_recipe]:
        mmsid = func(bag_name)
        if mmsid:
            return mmsid
    return None

    # mmsid = re.findall("(?<!^)(?<!\d)\d{8,19}(?!\d)", bag_name)
    # if mmsid:
    #     return mmsid[-1]
    # s3 = boto3.resource('s3')
    # print("Bucket Name in get_mmsid - {0}".format(bucket_name))
    # s3_key = "{0}/{1}/{2}".format('source', bag_name, 'bag-info.txt')
    # try:
    #     recipe_obj = s3.Object(bucket_name, s3_key)
    # except ClientError as e:
    #     logging.error(e)
    # #recipe_obj = s3.Object(bucket_name, s3_key)
    # bag_info = yaml.load(recipe_obj.get()['Body'].read())
    # try:
    #     mmsid = bag_info['FIELD_EXTERNAL_DESCRIPTION'].split()[-1].strip()
    #     print("bagname --- {0} = mmsid = {1}".format(bag_name,mmsid))
    # except KeyError:
    #     logging.error("Cannot determine mmsid for bag from bag-info: {0}".format(bag_name))
    #     return None
    # if re.match("^[0-9]{8,19}$", mmsid):  # check that we have an mmsid like value
    #     print("The matched value is=",re.match("^[0-9]{8,19}$", mmsid))
    #     return mmsid
    # return None

def get_marc_datafield(tag_id, xml_tree):
    try:
        return xml_tree.xpath("record/datafield[@tag={0}]".format(tag_id))[0]
    except IndexError:
        return None

def get_marc_subfield_text(tag_id, sub_code, xml_tree):
    """
    This is an internal function used for getting the sub field text from marc.xml.
    :param tag_id: tag_id
    :param sub_code: sub_code to get the title
    :param xml_tree: marc.xml file.
    :return: String or None
    """
    try:
        return xml_tree.xpath("record/datafield[@tag={0}]/subfield[@code='{1}']".format(tag_id, sub_code))[0].text
    except IndexError:
        return None

def get_title_from_marc(xml):
    """
    This field is used to get the title of the bag from marc.xml.
    :param xml: marc xml
    :return: String or None
    """
    if xml is None:
        return None
    tag_preferences = OrderedDict([
        # tag id, [ subfield codes ]
        (130, ['a']),
        (240, ['a']),
        (245, ['a', 'b'])
    ])
    xml_tree = ET.XML(xml)
    for tag in tag_preferences.keys():
        if get_marc_datafield(tag, xml_tree) is not None:
            title_parts = [get_marc_subfield_text(tag, code, xml_tree) for code in tag_preferences[tag]]
            title_parts = list(filter(partial(is_not, None), title_parts))  # remove None values
            if len(title_parts) > 1:
                title = " ".join(title_parts)

            else:
                title = title_parts[0]
            return title.strip(whitespace + "/,")

def get_marc_xml(mmsid,path,bib):
    """
    This function is used to write the marc.xml file read from the bib record into the specified path.
    :param mmsid: mmsid of the bag
    :param path: path to which the marc.xml must to written to.
    :param bib: bib record.
    :return: boolean
    """
    if bib is None:
        return False
    record = ET.fromstring(bib).find("record")
    record.attrib['xmlns'] = "http://www.loc.gov/MARC21/slim"
    if record.find(".//*[@tag='001']") is None and mmsid is not None:
        controlfield = ET.Element("controlfield",tag="001")
        controlfield.text=mmsid
        record.insert(1,controlfield)
    marc21 = ET.ElementTree(record)
    try:
        marc21.write(path+"/marc.xml", encoding='utf-8', xml_declaration=True)
        return True
    except IOError as err:
        logging.error(err)
        return False

def get_bib_record(mmsid):
    """
        Queries the ALMA with MMS ID to obtain corresponding MARC XML
        :param mmsid: mmsid of the bag
        :return bibrecord  or None
    """
    url = "https://api-na.hosted.exlibrisgroup.com/almaws/v1/bibs/{0}?expand=None&apikey={1}"

    apikey = os.environ.get('ALMA_READ_TOKEN')
    if not apikey:
        logging.error("Could not get Alma key")
        return None
    elif apikey and mmsid:
        try:
            response = requests.get(url.format(mmsid,apikey))
            if response.status_code == requests.codes.ok:
                return response.content
            else:
                logging.error("Alma server returned code: {0}".format(response.status_code))
                logging.error("Alma Response content: {0}".format(response.content))
                return None
        except requests.ConnectionError:
            logging.error("Alma Connection Error ")
            return None
    else:
        logging.error("No apikey and No mmsid")
        return None


