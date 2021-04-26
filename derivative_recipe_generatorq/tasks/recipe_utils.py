import bagit
import logging
from collections import OrderedDict
import json
from json import loads,dumps
from .utils import *
from .configs import base_dir
import jinja2
from inspect import cleandoc
from uuid import uuid5, NAMESPACE_DNS
repoUUID = uuid5(NAMESPACE_DNS, 'repository.ou.edu')

ou_derivative_bag_url = "https://bag.ou.edu/derivative"



def _get_path(taskid,bag_name,formatparams):
    return "{0}/oulib_tasks/{1}/derivative/{2}/{3}".format(base_dir,taskid,bag_name,formatparams)

def make_recipe(task_id,bag_name,mmsid,payload,formatparams,title):
    '''

    This function returns a dictionary with all the details needed by the recipe file.
    This is a helper function

    :param task_id: this id is used for locating the bag on the host side
    :param bag_name: name of the bag
    :param mmsid: this is mmsid of the bag provided as a dictionary eg. "mmsid":value
    :param payload: this is a dictionary and it has the directory structure inside the /data of the bag
    :param formatparams: a string generated from format parameters eg. jpeg_040_antialias
    :param title: title of the bag
    :return: json as a string containing the recipe details
    '''

    meta = OrderedDict()
    meta['recipe']= OrderedDict()
    meta['recipe']['import'] = 'book'
    meta['recipe']['update'] = 'false'
    meta['recipe']['uuid'] = str(uuid5(repoUUID,bag_name))
    meta['recipe']['label'] = title

    bib = get_bib_record(mmsid["mmsid"])
    logging.debug("Bib record value -- {0}".format(bib))
    path = _get_path(task_id,bag_name,formatparams)
    meta['recipe']['metadata']=OrderedDict();
    if get_marc_xml(mmsid["mmsid"],path,bib):
        meta['recipe']['metadata'] = {}
        if formatparams:
            meta['recipe']['metadata']['marcxml'] = "{0}/{1}/{2}/marc.xml".format(ou_derivative_bag_url, bag_name, formatparams)
        else:
            meta['recipe']['metadata']['marcxml'] = "{0}/{1}/marc.xml".format(ou_derivative_bag_url, bag_name)
    if title is None:
        logging.debug("Getting title from marc file")
        meta['recipe']['label']= get_title_from_marc(bib)
    meta['recipe']['pages'] = process_manifest(bag_name, payload, formatparams)
    logging.debug("Generated JSON:\n{0}".format(dumps(meta, indent=4)))
    return dumps(meta, indent=4, ensure_ascii=False).encode("UTF-8")

def process_manifest(bag_name,payload,formatparams=None):
    """
    This function generates the manifest required for the recipe file.
    :param bag_name: name of the bag
    :param payload: payload of the bag containing paths
    :param formatparams: e.g., jpeg_040_antialias
    :return: List of dictionaries e.g., [ {label: , "file": , "hash_key":} , ... ]
    """
    template = """
    	{"label" : {{ idx }},"file" : {% if formatparams %} "{{"{}/{}/{}/{}".format(ou_derivative_bag_url, bagname, formatparams, file[0])}}" {% else %} "{{"{}/{}/{}".format(ou_derivative_bag_url, bagname, filename)}}"{% endif%},{% for hash_key,hash_value in file[1].items() %}"{{ hash_key }}" : "{{ hash_value }}",{% endfor%} "exif":"{{"{}.exif.txt".format(file[0].split("/")[1])}}"}
    """
    pages=[]
    env = jinja2.Environment()
    tmplt = env.from_string(cleandoc(template))
    for idx, file in enumerate(payload.items()):
        page_str = tmplt.render(ou_derivative_bag_url=ou_derivative_bag_url, bagname=bag_name, idx=idx+1,
                                   formatparams=formatparams, file=file)
        page = json.loads(page_str)
        page['uuid'] = str(uuid5(repoUUID, "{0}/{1}".format(bag_name, file[0])))
        pages.append(page)
    return pages
