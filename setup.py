#import ez_setup
#ez_setup.use_setuptools()
from setuptools import setup, find_packages
setup(name='derivative_recipe_generatorq',
      version='0.1.0',
      packages= find_packages(),
      install_requires=[
          'celery>=4.4,<5',
          'bagit==1.7.0',
          'requests==2.25.0',
	  'pyyaml==5.3.1',
	  'pillow==7.0.0',
          'boto3~=1.17',
	  'lxml',
	  'jinja2',
      ],
)
