import random
from collections import defaultdict
from celery import chain
from celery.task import task
from glob import iglob
from celery import Celery
import celeryconfig
from uuid import uuid5, NAMESPACE_DNS
from shutil import rmtree
import datetime
from .derivative_utils import _params_as_string,_formatextension,_processimage
from .recipe_utils import _get_path
from .recipe_utils import *
import logging
import boto3,shutil




repoUUID = uuid5(NAMESPACE_DNS, 'repository.ou.edu')

# Assert correct generation
assert str(repoUUID) == "eb0ecf41-a457-5220-893a-08b7604b7110"


app = Celery()
app.config_from_object(celeryconfig)

mount_point="/mnt"
ou_derivative_bag_url = "https://bag.ou.edu/derivative"
recipe_url = ou_derivative_bag_url + "/{0}/{1}/{2}.json"
base_url = "https://cc.lib.ou.edu"
api_url = "{0}/api".format(base_url)
search_url = "{0}?query={{\"filter\": {{\"bag\": \"{1}\"}}}}"

basedir = "/data/web_data/static"

bagList=[]

def getAllBags():
    response = requests.get('{0}/catalog/data/catalog/digital_objects/?query={{"filter":{{"department":"DigiLab","project":{{"$ne":"private"}},"locations.s3.exists":{{"$eq":true}},"derivatives.jpeg_040_antialias.recipe":{{"$exists":false,"$error":ne}}}}}}&format=json&page_size=0'.format(api_url))
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
def automate(outformat,filter,scale=None,crop=None,force_overwrite=False,bag=None):
    """
    This automates the process of derivative creation.
    :return: string "kicked off or not"
    """
    #If bag is given is then kickoff separate chain.

    for bag in getSample():
        result = chain(read_source_update_derivative.s(bag, "source", "derivative", outformat, filter, scale,crop,force_overwrite),
                       process_recipe.s())
        result.delay()
    return "automate kicked off"

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
        recipe =  loads(f.read())
    return [page['file'] for page in recipe['recipe']['pages']]

@task(bind=True)
def read_source_update_derivative(self,bags,s3_source="source",s3_destination="derivative",outformat="TIFF",filter='ANTIALIAS',scale=None, crop=None,force_overwrite=False):
    """

    This function is the starting function of the workflow used for derivative generation of the files.

    :args
    bags = List containing bagnames eg : [bag1,bag2...]
    s3_source = source directory.
    s3_destination : destionation directory.
    outformat = "TIFF or JPEG"
    filter = "ANTALIAS" - filter type of the image.
    scale = At what scale do you need the reduction of the size - eg 0.40 or 0.20
    crop = size in which the image needs to be cropped, Provide it as a list - eg - [10,10,20,40]
    force_overwrite = overwrite the derivative bag already if it was already created with the
    previous paramaters. -eg: true.

    :returns dictionary with s3_destionation , bags_with_mmsid:{} , format_params as keys and there values.
    """

    task_id = str(self.request.id)
    resultpath = os.path.join(basedir, 'oulib_tasks/', task_id)
    os.makedirs(resultpath)
    s3 = boto3.resource('s3')
    # hardcode bucket name as of now , get from Env or Log an error if bucket name is not provided.
    bucket = s3.Bucket('ul-cc')
    bags_with_mmsids = OrderedDict()
    if type(bags) == 'str':
        bags = [bags]
    for bag in bags:
        format_params = _params_as_string(outformat,filter,scale,crop)
        #code for boto3
        src_input = os.path.join(resultpath, 'src/', bag)
        output = os.path.join(resultpath, 'derivative/', bag)
        print(output)
        os.makedirs(src_input)
        os.makedirs(output)
        source_location = "{0}/{1}/data".format(s3_source, bag)
        filter_loc = "{0}/{1}".format(s3_source, bag)
        #path_to_bag = "{0}/{1}/{2}/".format(mount_point,s3_source,bag)
        mmsid =get_mmsid(bag,None)
        if mmsid:
            bags_with_mmsids[bag]=OrderedDict()
            bags_with_mmsids[bag]['mmsid'] = mmsid
            file_extensions = ["tif","TIFF","TIF","tiff"]
            #file_paths=[]
            # get the filename and then download it and search.
            #path_to_manifest_file = "{1}/{2}/manifest*.txt".format(s3_source,bag)
            #path_to_bag = "{0}/{1}/{2}/data/".format(mount_point, s3_source, bag)
            #for file in glob.glob(path_to_manifest_file):
            status_flag=False
            for obj in bucket.objects.filter(Prefix=filter_loc):
                if 'manifest-md5.txt' == obj.key.split('/')[-1]:
                    inpath = "{0}/{1}".format(src_input, obj.key.split('/')[-1])
                    s3.meta.client.download_file(bucket.name, obj.key, inpath)
                    if(getIntersection(inpath)):
                        logging.error("Conflict in bag - {0} : Ambiguous file names (eg. 001.tif , 001.tiff)".format(bag))
                        #just logging but not capturing the details in unsuccessfull bag
                        status_flag=True;
                        break;

                # this code is not required
                # now try to use the filter one
                else:
                    continue;

            if status_flag:
                continue
            """
            if os.path.exists("{0}/derivative/{1}/{2}".format(mount_point, bag, format_params)) and force_overwrite:
                rmtree(outdir)
            if os.path.exists("{0}/derivative/{1}/{2}".format(mount_point, bag, format_params)) and not force_overwrite:
                raise Exception("derivative already exists and force_overwrite is set to false")
            if not os.path.exists("{0}/derivative/{1}/{2}".format(mount_point, bag, format_params)):
                os.makedirs(outdir)"""
            for obj in bucket.objects.filter(Prefix=source_location):
                filename = obj.key;
                if filename.split('.')[-1].lower() in file_extensions:
                    inpath = "{0}/{1}".format(src_input, filename.split('/')[-1])
                    s3.meta.client.download_file(bucket.name, filename, inpath)
                    outpath = "{0}/{1}/{2}.{3}".format(output,format_params,filename.split('/')[-1].split('.')[0].lower(),
                                                   _formatextension(outformat))
                    #outpath = '{0}/{1}/{2}/{3}/{4}.{5}'.format(mount_point,"derivative",bag,format_params,file.split('/')[-1].split('.')[0].lower(),_formatextension(outformat))
                    processimage(inpath=inpath,outpath=outpath,outformat=outformat,filter=filter,scale=scale,crop=crop)
                    os.remove(inpath)
        else:
            update_catalog(task_id,bag,format_params,mmsid)
        #shutil.rmtree(os.path.join(resultpath, 'src/', bag))

        # except Exception as e:
        #     logging.error(e)
        #     logging.error("handled exception here for - - {0}".format(bag))
    return {"s3_destination": s3_destination,"task_id":task_id,
            "bags":bags_with_mmsids,"format_params":format_params}

def getIntersection(file):
    """
    This method is used for knowing if their are any name conflicts inside the manifest file of each bag.
    name conflict examples - [ 001.tif , 001.tiff] or [001.TIF , 001.tiff] or [001.TIFF , 001.tif] or [001.TIF , 001.TIFF]
    :param file: manifest file of each bag.
    :return: boolean true or false.
    """
    ListOfFileNames = []
    with open(file, "r") as f:
        lines = f.readlines();
        for line in lines:
            line = line.strip();
            ListOfFileNames.append(line.split("/")[-1])
    listOfTif = [name.split(".")[0] for name in ListOfFileNames if name.endswith(".tif") or name.endswith(".TIF")]
    listOfTiff = [name.split(".")[0] for name in ListOfFileNames if name.endswith(".tiff") or name.endswith(".TIFF")]
    intersectionList = list(set(listOfTiff) & set(listOfTif))
    if(len(intersectionList) == 0):
        return False;
    else:
        return True;

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

    :param bag: bag name
    :param paramstring: eg. jpeg_040_antialias
    :param mmsid: mmsid of the bag
    :return: boolean. True for successful updation. False for failure.
    """
    db_client = app.backend.database.client
    collection = db_client.cybercom.catalog
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
    """
        This function generates the recipe file and returns the json stats of which bags are successful
        and which are not.

        params:
        derivative_args:The arguments returned by read_source_update_derivative function.
    """
    s3_bucket = 'ul-cc'
    s3_destination = 'derivative'
    bags = derivative_args.get('bags') #bags = { "bagname1" : { "mmsid": value} , "bagName2":{"mmsid":value}, ..}
    format_params = derivative_args.get('format_params')
    task_id = derivative_args.get('task_id')
    status_dict = defaultdict(list)
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(s3_bucket)
    for bag_name,mmsid in bags.items():
        if not mmsid:
           status_dict["unsuccessful_bags"].append(bag_name)
           continue
        bag_derivative(task_id,bag_name,format_params)
        recipe_file_creation(task_id,bag_name,mmsid,format_params)
        bagpath = "{0}/oulib_tasks/{1}/derivative/{2}".format(basedir, task_id, bag_name)
        logging.info("Accessing bag at: {0}".format(bagpath))
        for filepath in iglob("{0}/*.*".format(bagpath)):
            filename = filepath.split('/')[-1].lower()
            s3_key = "{0}/{1}/{2}/{3}".format(s3_destination, bag_name, format_params, filename)
            logging.info("Saving {0} to {1}".format(filename, s3_key))
            s3.meta.client.upload_file(filepath, bucket.name, s3_key)
        for filepath in iglob("{0}/data/*.*".format(bagpath)):
            filename = filepath.split('/')[-1].lower()
            s3_key = "{0}/{1}/{2}/data/{3}".format(s3_destination, bag_name, format_params, filename)
            logging.info("Saving {0} to {1}".format(filename, s3_key))
            s3.meta.client.upload_file(filepath, bucket.name, s3_key)
        status = update_catalog(task_id,bag_name,format_params,mmsid["mmsid"])
        if(not status):
           logging.error("The data of the bag - {0} not updated in catalog - "
                         "May be the record is not found or something is failed".format(bag_name))
           status_dict["unsuccessful_bags"].append(bag_name)
        else:
            status_dict["successful_bags"].append(bag_name)
        if rmlocal is True:
            rmtree("{0}/oulib_tasks/{1}/derivative/{2}".format(basedir, task_id,bag_name))
    return "Derivative-Recipe stats : {0}".format(str(status_dict))

@task
def bag_derivative(task_id,bag_name,format_params,update_manifest=True):
    """
        This methods create a bag for the derivative folder
        and updates the bag-info.txt generated
        args :
            bagName: str
            update_manifest : boolean
    """

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
    """
        This method creates the recipe.json file and updates it into the derivative folder of the bag
        args:
            bag_name: str - name of the bag
            mmsid: dictionary "mmsid":value
            formatparams :  str eg . jpeg_040_antialias
    """
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
def insert_data_into_mongoDB():
    """
    This is a test function used for inserting records into local database.

    :return:
    """
    response = requests.get('https://cc.lib.ou.edu/api/catalog/data/catalog/digital_objects/?query={"filter":{"department":"DigiLab","project":{"$ne":"private"},"locations.s3.exists":{"$eq":true}}}&format=json&page_size=0')
    jobj = response.json()
    results = jobj.get('results')
    db_client = app.backend.database.client
    print(db_client.database_names())
    database = db_client["cybercom"]

    if not "catalog" in db_client.cybercom.collection_names():
        mycol = database["catalog"]
        for data in results:
            mycol.insert_one(data)
        return "successful"
    return "already exists"
   # mydict = {"name": "hello", "address": "Norman"}
    #x = mycol.insert_one(mydict)


