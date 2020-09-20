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


def get_mmsid(bag_name,path_to_bag=None):
    """

    :param bag_name: name of the bag
    :param path_to_bag: path to that bag
    :return: mmsid or None
    """
    mmsid = re.findall("(?<!^)(?<!\d)\d{8,19}(?!\d)", bag_name)
    if mmsid:
        return mmsid[-1]
    fh =open(path_to_bag+"bag-info.txt")
    bag_info = yaml.load(fh)
    try:
        mmsid = bag_info['FIELD_EXTERNAL_DESCRIPTION'].split()[-1].strip()
        print(type(mmsid))
        print(mmsid)
    except KeyError:
        logging.error("Cannot determine mmsid for bag from bag-info: {0}".format(bag_name))
        return None
    if re.match("^[0-9]{8,19}$", mmsid):  # check that we have an mmsid like value
        print("matching value -- ",re.match("^[0-9]{8,19}$", mmsid))
        return mmsid
    return None

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

    apikey = os.environ.get('ALMA_KEY')
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


