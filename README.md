# derivative-recipe-generatorq

This code is used for generating derivatives of images , generating the recipe files and finally updating the catalog.


## Functionality of tasks.py

This python package consists of all the tasks which are exposed on the Django api task queue. It is the core file of this package.

## Functionality of each method in tasks.py

#### getSample():
This method returns a list consisting of a sample of the bags which are needed to be processed.


#### automate(outformat,filter,scale=None,crop=None,force_overwrite=False,bag=None):
This method triggers the workflow containing the chained tasks (read_source_update_derivative(bag, "source", "derivative", outformat, filter, scale,crop,force_overwrite) , process_recipe()) on each of the bags returned by getSample(). 

#### read_source_update_derivative(bags,s3_source="source",s3_destination="derivative",outformat="TIFF",filter='ANTIALIAS',scale=None, crop=None,force_overwrite=False):
This method takes the list of bags passed from the automate method or can be kicked off separately with a list of bags. We need to provide the s3_source(The directory name from which source files are derived) , s3_destination(The destination folder into which the derivative processed images are stored) , outformat(The format into which the images of the bags needs to be processed), filter( The filter which is needed to be applied on the images) ,scale (The scale to which the image is needed to be reduced -- e.g., 0.40 (40% scaling)) , crop (For cropping the final image into this size e.g., [10,10,10,10]), force_overwrite (Boolean value upon setting it removes already derived images in amazon s3).

This method internally calls several methods like get_mmsid(),_params_as_string(),getIntersection(),process_image(). Finally it returns the list of bags along with their mmsids to the process_recipe() task so that it can generate recipe files for those bags and update the catalog.

##### Flow of Control:

For each bag in the list of bags:

###### Step-1
get_mmsid(bag) --> If mmsid of the bag is not found then an error message with the following status "mmsid is not found " is updated in the catalog and contols moves on to the next bag.

###### Step-2
If get_mmsid(bag) returns a mmsid:

###### Step-3
Then we go ahead and get all the paths of files which need to processed from the source. If there are ambiguous filenames then the error is logged and we move on to the next bag.

###### Step-4
If there are no ambiguous files then we get all the files paths and try to process them , 
Here we have the following scenarios, 
  1) The destination don't have the derived images with the format_params mentioned , then we go ahead and process.
  2) If the destination already has derived images with the same format_parameters then we check whether we are given the premission to force_overwrite.
       - If force_overwrite:
             - Go ahead and process
       - else:
             - raise Exception and move on to next bag.

###### Step-5
We have got all the required files, 
for each of the file in files we call. 
    processimage(inpath=file,outpath=outpath,outformat=outformat,filter=filter,scale=scale,crop=crop)

###### Step-6
Finally we return the a JSON with list of bags and their mmsids , s3_destination , format_params to the process_recipe() task.

#### getIntersection(file):
This method is used for knowing if there are any ambiguous file names with different extensions.

#### processimage(inpath, outpath, outformat="TIFF", filter="ANTIALIAS", scale=None, crop=None):
This method is kind of a wrapper.Called inside the read_source_update_derivative method this method internally calls another method called _processimage().
It takes all the format parameters passed ot the read_source_update_derivative method() along the inpath and outpath.

#### process_recipe(derivative_args):
This method is the second task of the automate chain. It is used to for generating the recipe file and finally update_catalog with the required data.

For each bag in the parameters returned by read_source_update_derivative(). The following 
Internal methods are called: bag_derivative(), recipe_file_creation(), update_catalog()

##### Flow of Control

For each bag in the derivative args:

###### Step-1
Call  bag_derivative(bag_name,format_params), here we are bagging the bag with all the required hashing. If there is an error in bag_creation ,then we are logging it.

###### Step-2
Call recipe_file_creation(bag_name,mmsid,format_params,title=None), here are trying to generate the recipe file of the entire bag which the derived image data.

###### Step-3
On successfull recipe file creation we are calling the update_catalog(bag,paramstring,mmsid=None), If the bag data is updated properly in the catalog , then we add the bag into successfull bags list else we add it to unsuccessfull bags list.

###### Step-4
Finally return a dictionary with successful and unsuccessful bags list.

#### bag_derivative(bag_name,format_params,update_manifest=True):
This method creates hashes and creates proper manifests of the bag which is passed to it.

#### recipe_file_creation(bag_name,mmsid,format_params,title=None):
This method internally calls make_recipe() method which returns the data required by the recipe file . Finally it writes returned data to the recipe_file and saves it in the bag.

#### update_catalog(bag,paramstring,mmsid=None):
This method does the following functionality , it takes bag, paramstring , mmsid of the bag and pulls the appropriate document from the catalog and updates it.
If the mmsid of the bag is not found then it updates the catalog with a error. If the mmsid is passed to this method but for any other reason if the catalog is not updated then we return a false status or else we return true.


## Functionality of derivative_utils.py

This python file provides the utility support for derivative generation process.

## Functionality of each method in derivative_utils.py

#### _formatextension(imageformat):
Returns the file extension of the provided image format.

#### _params_as_string(outformat="", filter="", scale=None, crop=None):
This method just returns the formatted string with the parameters provided in the read_source_update_derivative().

#### _processimage(inpath=inpath,outpath=outpath,outformat=outformat,filter=filter,scale=scale,crop=crop):
This method does the actually processing of the images and save it into the outpath provided in the function. It internally uses Image library of python and does all the required processing.

## Functionality of recipe_utils.py

This python file provides the utility support for recipe_file creation.

## Functionality of each method in recipe_utils.py

#### _get_path(bag_name,formatparams):
Returns the path to bag with respect to the mount point.

#### make_recipe(bag_name,mmsid,payload,formatparams,title):
This is one of the crucial method in recipe file generation. It makes use of methods in the utils.py for getting the appropriate fields and then updates the dictionary with those values. Finally this method returns a String with all the required data in the form of a dictionary.

#### process_manifest(bag_name,payload,formatparams=None):
This method makes use of the jinja templating technique and reads all the data in the payload sent along with bag and generates a list with each element, being a processed_dictionary of the files in the payload. This method is called in the make_recipe method to construct the dictionary needed for the recipe file.


## Functionality of utils.py

This python file provides the utility support for both derivative generation and recipe_file creation.

## Functionality of each method in utils.py

#### get_mmsid(bag_name,path_to_bag=None):
This method searches for the mmsid of each bag in the bag-info.txt or whether it is appended to its name. It also checks if the mmsid is of the appropriate length and returns it. If not , a None value is returned. It is the first method which is called in the derivative generation process and plays a key role in many other methods.

#### get_bib_record(mmsid):
This method returns the bib_record by quering the ALMA. If there is some error in acquiring the bib_record from the ALMA(it may be because of wrong key or error response from ALMA or couldn't connect to ALMA) we return a None value.

#### get_marc_xml(mmsid,path,bib):
This method is used for writing the marc.xml which is the content retrieved from bib_record.The bib_record is specific to the bag and is pulled from the ALMA using the mmsid of the bag. None value is returned if bib_record is not found.

#### get_title_from_marc(xml):
This method is used for fetching the title of the book from the marc.xml file. This method makes use of the get_marc_datafield(tag_id, xml_tree), get_marc_subfield_text(tag_id, sub_code, xml_tree) to get the title. None value is returned if xml is not found.

#### get_marc_datafield(tag_id, xml_tree):
Returns a datafield of the xml_tree

#### get_marc_subfield_text(tag_id, sub_code, xml_tree):
This method is used to get the title from the marc.xml which is broken into several parts in the xml.
