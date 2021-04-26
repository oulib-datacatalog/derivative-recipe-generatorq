import random
from collections import defaultdict
from celery import chain
from celery.task import task
from glob import iglob
from celery import Celery
import celeryconfig
from uuid import uuid5, NAMESPACE_DNS
import json
from shutil import rmtree
import datetime
from .derivative_utils import _params_as_string,_formatextension,_processimage
from .recipe_utils import _get_path
from .recipe_utils import *
import logging
import boto3,botocore,shutil
import re
from botocore.exceptions import ClientError
from celery import signature
from .configs import base_url, recipe_url


repoUUID = uuid5(NAMESPACE_DNS, 'repository.ou.edu')

# Assert correct generation
assert str(repoUUID) == "eb0ecf41-a457-5220-893a-08b7604b7110"


app = Celery()
app.config_from_object(celeryconfig)

#ou_derivative_bag_url = "https://bag.ou.edu/derivative"
#recipe_url = ou_derivative_bag_url + "/{0}/{1}/{2}.json"
#base_url = "https://cc.lib.ou.edu"
#api_url = "{0}/api".format(base_url)
search_url = "{0}?query={{\"filter\": {{\"bag\": \"{1}\"}}}}"

basedir = "/data/cybercom_output"
bagList=[]

def getAllBags():
    response = requests.get('{0}/catalog/data/catalog/digital_objects/?action=distinct&field=bag&query={{"filter":{{"department":"DigiLab","project":{{"$ne":"private"}},"locations.s3.exists":{{"$eq":true}},"derivatives.jpeg_040_antialias.recipe":{{"$exists":false,"$error":ne}}}}}}&format=json&page_size=0'.format(base_url))
    jobj = response.json()
    results=jobj.get('results')
    for obj in results:
        yield obj.get('bag')

@task
def getSample(size=4):
    try:
        #list(random.sample(list(getAllBags()), size))
        yield ['Apian_1545','Accum_1820','Beyer_1562','Abbati_1703']
    except:
        return getAllBags()

@task
def automate(outformat=None,filter=None,scale=None,crop=None,bag=None):
    """
    This automates the process of derivative creation.
    :return: string "kicked off or not"
    """
    #If bag is given is then kickoff separate chain.

    for bag in getSample():
        result = chain(read_source_update_derivative.s(bag,None,"source", "derivative", "JPEG", filter, scale,crop),
                       process_recipe.s())
    result.delay()

def listpagefiles(task_id,bag_name, paramstring):
    """
    This is a helper function which returns the list of pages.

    :param bag_name: Name of the bag
    :param paramstring: eg., jpeg_040_antialias
    :return: list of pagespaths [ '/x/y' ,'abc/xyz/' ... ]
    """
    filename = "{0}.json".format(bag_name)
    path=_get_path(task_id,bag_name, paramstring)
    recipe_json = os.path.join(path,filename)
    with open(recipe_json,"r") as f:
        recipe = loads(f.read())
    return [page['file'] for page in recipe['recipe']['pages']]

@task(bind=True)
def read_source_update_derivative(self,bags,bucket_name=None,s3_source="source",s3_destination="derivative",outformat="TIFF",filter='ANTIALIAS',scale=None, crop=None):
    """

    This function is the starting function of the workflow used for derivative generation of the files.

    :args
    bags = List containing bagnames eg : [bag1,bag2...]
    bucket_name = name of the s3 bucket
    s3_source = source directory.
    s3_destination : destionation directory.
    outformat = "TIFF or JPEG"
    filter = "ANTALIAS" - filter type of the image.
    scale = At what scale do you need the reduction of the size - eg 0.40 or 0.20
    crop = size in which the image needs to be cropped, Provide it as a list - eg - [10,10,20,40]
    :returns dictionary with s3_destionation , bags_with_mmsid:{} , format_params as keys and there values.
    """

    task_id = str(self.request.id)
    resultpath = os.path.join(basedir, 'oulib_tasks/', task_id)
    os.makedirs(resultpath)
    s3 = boto3.resource('s3')
    #FIXME: hardcode bucket name as of now , get from Env or Log an error if bucket name is not provided.
    if bucket_name is None:
        bucket_name=os.environ.get('AWS_BUCKET_NAME','ul-bagit')
    print("bucket-name == {0}".format(bucket_name))
    bucket = s3.Bucket(bucket_name)
    bags_with_mmsids = OrderedDict()
    bags_status=OrderedDict()
    bags_status["Failed"] = []
    bags_status["Success"] = []
    if type(bags) == str:
        bags = [bags]
    print("Bags list === {0}".format(bags))
    for bag in bags:
        format_params = _params_as_string(outformat,filter,scale,crop)
        #code for boto3
        src_input = os.path.join(resultpath, 'src/', bag)
        output = os.path.join(resultpath, 'derivative/', bag,format_params)
        os.makedirs(src_input)
        os.makedirs(output)
        source_location = "{0}/{1}/data".format(s3_source, bag)
        filter_loc = "{0}/{1}/{2}".format(s3_source, bag,"data")
        mmsid =get_mmsid(bag)
        if mmsid:
            bags_with_mmsids[bag]=OrderedDict()
            bags_with_mmsids[bag]['mmsid'] = mmsid
            file_extensions = ["tif","TIFF","TIF","tiff"]

            status_flag=False
            files = []
            for obj in bucket.objects.filter(Prefix=filter_loc):
                if obj.key.split('/')[-1].split('.')[-1] in file_extensions:
                    files.append(obj.key.split('/')[-1].split('.')[0])

            if len(files) != len(set(files)):
                logging.error("Conflict in bag - {0} : Ambiguous file names (eg. 001.tif , 001.tiff)".format(bag))
                status_flag=True;
                status_bag = defaultdict()
                status_bag["name"] =bag
                status_bag["reason"] = "Conflict in file names (eg. 001.tif , 001.tiff)"
                bags_status["Failed"].append(status_bag)
            if status_flag:
                continue
            for obj in bucket.objects.filter(Prefix=source_location):
                filename = obj.key;
                if re.search("(original|orig)\.\w{3,4}$", filename, re.IGNORECASE):
                    # skip files similar to 001_orig.tif, 001.orig.tif, 001_Original.tiff, 001.original.jpg,  etc.
                    continue
                #FIXME: Check this code for checking the filenames if it starts with '.'
                if re.search("^\.", filename.split("/")[-1]):
                    # skip files starting with a period
                    continue
                if re.search("(tif|tiff)$", filename, re.IGNORECASE):
                    inpath = "{0}/{1}".format(src_input, filename.split('/')[-1])
                    try:
                        s3.meta.client.download_file(bucket.name, filename, inpath)
                    except ClientError as e:
                        logging.error(e)
                    outpath = "{0}/{1}.{2}".format(output,filename.split('/')[-1].split('.')[0].lower(),
                                                   _formatextension(outformat))
                    processimage(inpath=inpath,outpath=outpath,outformat=outformat,filter=filter,scale=scale,crop=crop)
                    os.remove(inpath)
        else:
            status=update_catalog(task_id,bag,format_params,mmsid)
            if (not status):
                logging.error("The data of the bag - {0} not updated in catalog".format(bag))
            status_bag = defaultdict()
            status_bag["name"] = bag
            status_bag["reason"] = "No mmsid found"
            bags_status["Failed"].append(status_bag)
        shutil.rmtree(os.path.join(resultpath, 'src/', bag))

    return {"s3_destination": s3_destination,"task_id":task_id,
            "bags":bags_with_mmsids,"format_params":format_params,"bags_status":bags_status}

@task
def processimage(inpath, outpath, outformat="TIFF", filter="ANTIALIAS", scale=None, crop=None):
    """
    Digilab TIFF derivative Task

    args:
      inpath - path string to input image
      outpath - path string to output image
      outformat - string representation of image format - default is "TIFF"
      scale - percentage to scale by represented as a decimal
      filter - string representing filter to apply to resized image - default is "ANTIALIAS"
      crop - list of coordinates to crop from - i.e. [10, 10, 200, 200]
    """
    _processimage(inpath=inpath,
                  outpath=outpath,
                  outformat=outformat,
                  filter=filter,
                  scale=scale,
                  crop=crop
                  )

@task
def update_catalog(task_id,bag,paramstring,mmsid=None):
    """
    :param task_id: task_id used for getting the mmsid
    :param bag: bag name
    :param paramstring: eg. jpeg_040_antialias
    :param mmsid: mmsid of the bag
    :return: boolean. True for successful updation. False for failure.
    """
    db_client = app.backend.database.client
    collection = db_client.catalog.digital_objects
    query = {"bag": bag}
    document = collection.find_one(query)
    if document == None:
        return False
    document_id = document['_id']
    myquery = {"_id":document_id}

    if mmsid == None:
        if "error" in document.keys():
            document["error"].append("mmsid not found")
        else:
            document.update({"error": ["mmsid not found"]})
        update_mmsid_error = {
            "$set":
                {
                    "error": document["error"]
                }
        }
        status = collection.update_one(myquery,update_mmsid_error)
        return status.raw_result['nModified'] != 0
    if paramstring not in document["derivatives"]:
        document["derivatives"][paramstring]={}
    #ask whether bag_name needs to be lower.
    document["derivatives"][paramstring]["recipe"] = recipe_url.format(bag, paramstring, bag)
    document["derivatives"][paramstring]["datetime"] = datetime.datetime.utcnow().isoformat()
    document["derivatives"][paramstring]["pages"] = listpagefiles(task_id,bag, paramstring)
    update_derivative_values = {
        "$set":
            {
                "derivatives": document["derivatives"]
            }
    }
    general_update_status = collection.update_one(myquery,update_derivative_values)
    return general_update_status.raw_result['nModified'] !=0

@task
def process_recipe(derivative_args,rmlocal=True):
    '''
    This function generates the recipe file and returns the json stats of which bags are successful
    and which have failed.
    :param derivative_args: The arguments returned by read_source_update_derivative function.
    :param rmlocal: default value is True. It removes the local directory structure created on the host side.
    :return: Derivative and Recipe Statistics are returned.
    '''

    s3_bucket = 'ul-cc'
    s3_destination = 'derivative'
    if type(derivative_args) == 'str':
        derivative_args = json.loads(derivative_args)
    bags = derivative_args.get('bags') #bags = { "bagname1" : { "mmsid": value} , "bagName2":{"mmsid":value}, ..}
    format_params = derivative_args.get('format_params')
    task_id = derivative_args.get('task_id')
    bags_status=derivative_args.get('bags_status')
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(s3_bucket)
    failed_bags = [bag.get("name") for bag in bags_status['Failed'] if bag.get("name") is not None]
    for bag_name,mmsid in bags.items():
        if bag_name not in failed_bags:
            if not mmsid:
                status_bag = defaultdict()
                status_bag["name"] = bag_name
                status_bag["reason"] = "No mmsid found"
                bags_status["Failed"].append(status_bag)
                continue
            bag_derivative(task_id,bag_name,format_params)
            recipe_file_creation(task_id,bag_name,mmsid,format_params)
            bagpath = "{0}/oulib_tasks/{1}/derivative/{2}/{3}".format(basedir, task_id, bag_name,format_params)
            logging.info("Accessing bag at: {0}".format(bagpath))
            for filepath in iglob("{0}/*.*".format(bagpath)):
                filename = filepath.split('/')[-1].lower()
                s3_key = "{0}/{1}/{2}/{3}".format(s3_destination, bag_name, format_params, filename)
                logging.info("Saving {0} to {1}".format(filename, s3_key))
                try:
                    s3.meta.client.upload_file(filepath, bucket.name, s3_key)
                except ClientError as e:
                    logging.error(e)
            for filepath in iglob("{0}/data/*.*".format(bagpath)):
                filename = filepath.split('/')[-1].lower()
                s3_key = "{0}/{1}/{2}/data/{3}".format(s3_destination, bag_name, format_params, filename)
                logging.info("Saving {0} to {1}".format(filename, s3_key))
                try:
                    s3.meta.client.upload_file(filepath, bucket.name, s3_key)
                except ClientError as e:
                    logging.error(e)
            status = update_catalog(task_id,bag_name,format_params,mmsid["mmsid"])
            if(not status):
               logging.error("The data of the bag - {0} not updated in catalog - "
                             "May be the record is not found or something is failed".format(bag_name))
               status_bag = defaultdict()
               status_bag["name"] = bag_name
               status_bag["reason"] = "The data of the bag not updated in catalog , May be the record is not found or something is failed"
               bags_status["Failed"].append(status_bag)
            else:
                bags_status["Success"].append(bag_name)
            if rmlocal is True:
                rmtree("{0}/oulib_tasks/{1}/derivative/{2}".format(basedir, task_id,bag_name))
    return {"Derivative-Recipe stats":"{0}".format(str(bags_status))}

@task
def bag_derivative(task_id,bag_name,format_params,update_manifest=True):
    '''
    This methods create a bag for the derivative folder
        and updates the bag-info.txt generated

    :param task_id: used for accessing the bag location on the host side
    :param bag_name: name of the bag eg. Abbati_1703
    :param format_params: used for accessing the bag location and it is of the type eg.jpeg_040_antialias
    :param update_manifest: default value is True. It creates the updated manifest file.
    :return: doesn't return anything
    '''

    path = _get_path(task_id,bag_name,format_params)
    try:
        bag=bagit.Bag(path)
    except bagit.BagError:
        bag = bagit.make_bag(path)
    bag.info['External-Description'] = bag_name
    bag.info['External-Identifier'] = 'University of Oklahoma Libraries'

    try:
        bag.save(manifests=update_manifest)
    except IOError as err:
        logging.error(err)


@task
def recipe_file_creation(task_id,bag_name,mmsid,format_params,title=None):
    '''
    This method creates the recipe.json file and updates it into the derivative folder of the bag

    :param task_id: This id is used for getting the path to the bag
    :param bag_name: name of the bag
    :param mmsid: dictionary "mmsid":value
    :param format_params: str eg . jpeg_040_antialias
    :param title: used as label for the bag.
    :return: doesn't return anything
    '''

    path = _get_path(task_id,bag_name,format_params)
    try:
        bag = bagit.Bag(path)
        payload = bag.payload_entries()
        recipefile = "{0}/{1}.json".format(path,bag_name)
        recipe=make_recipe(task_id,bag_name,mmsid,payload,format_params,title)
        logging.debug("Writing recipe to: {0}".format(recipefile))
        with open(recipefile,"w") as f:
            f.write(recipe.decode("UTF-8"))
        bag.save()
    except bagit.BagError:
        logging.debug("Not a bag: {0}".format(path))
    except IOError as err:
        logging.error(err)


@task
def insert_data_into_mongoDB(database_name='catalog',collection_name='digital_objects'):
    """
    This is a test function used for inserting records into local database.
    :param database_name: name of mongodb database (default is 'catalog')
    :param collection_name: name of collection in mongodb databse (default is 'digital_objects')
    :return: string 'successful' or 'already exists'
    """
    response = requests.get('https://cc.lib.ou.edu/api/catalog/data/catalog/digital_objects/?query={"filter":{"department":"DigiLab","project":{"$ne":"private"},"locations.s3.exists":{"$eq":true}}}&format=json&page_size=0')
    jobj = response.json()
    results = jobj.get('results')
    db_client = app.backend.database.client
    print(db_client.database_names())
    database = db_client[database_name]

    if not collection_name in db_client[database_name].collection_names():
        mycol = database[collection_name]
        for data in results:
            mycol.insert_one(data)
        return "successful"
    return "already exists"
   # mydict = {"name": "hello", "address": "Norman"}
    #x = mycol.insert_one(mydict)


