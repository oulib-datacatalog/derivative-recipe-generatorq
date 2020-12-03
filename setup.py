#import ez_setup
#ez_setup.use_setuptools()
from setuptools import setup, find_packages
setup(name='derivative-recipe-generatorq',
      version='0.0.1',
      packages= find_packages(),
      install_requires=[
          'celery',
          'bagit==1.7.0',
          'requests==2.25.0',
	  'pillow==7.0.0',
          'boto3~=1.6',
	  'lxml',
	  'jinja2',
      ],
)
