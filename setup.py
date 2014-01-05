#!/usr/bin/env python

from distutils.core import setup

setup(name='schirm',
      version='0.1',
      author="Erik Soehnel",
      author_email="eriksoehnel@googlemail.com",
      url="https://github.com/hoeck/schirm",
      provides=['schirm', 'schirmclient'],
      scripts=["bin/schirm"],
      packages=['schirm', 'schirm.pyte', 'schirm.ws4py', 'schirm.chan'],
      package_dir={'schirm':'schirm',
                   '':'support'},
      py_modules=['schirmclient'],
      package_data={'schirm':['resources/*']},
      )
