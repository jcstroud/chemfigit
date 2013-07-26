#! /usr/bin/env python

import os
import shutil
import tempfile
import subprocess
import logging
import time
import re
import textwrap

import phyles

from _version import __version__


FORMATS = ["pdf", "svg", "png"]

class ChemFigitError(Exception):
  pass

class TextSub(dict):
  """
  Create a regular expression from the dictionary keys

  Adapted from
  http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/81330
  """
  def __init__(self, data=None):
    self.re = None
    self.regex = None
    self.update(data)
    self.compile()
  def compile(self):
    if len(self) > 0:
      tmp = "(%s)" % "|".join(map(re.escape,
                                  self.keys()))
      if self.re != tmp:
          self.re = tmp
          self.regex = re.compile(self.re)
  def __call__(self, match):
    return self[match.string[match.start():match.end()]]
  def sub(self, s):
    if len(self) == 0:
        return s
    return self.regex.sub(self, s)

def multisub(text, adict):
  ts = TextSub(adict)
  return ts.sub(text)

def optional_file(a):
  if a == "None":
      a = None
  elif not ((a is None) or (isinstance(a, basestring))):
      raise ValueError("%s is not a string or None" % a)
  return a

def output_formats(alist):
  for a in alist:
    if a not in FORMATS:
      raise ValueError("Format '%s' is not in %s." % (a, FORMATS))
  return alist

def process_includes(cfg, tex):
  input_rgx = re.compile(r'\input{([^}]+)}')
  originals = input_rgx.findall(tex)
  targets = [os.path.basename(orig) for orig in originals]
  substitutions = dict(zip(originals, targets))
  for orig in originals:
    shutil.copy(orig, cfg['temp_dir'])
  return multisub(tex, substitutions)

def do_pdf(cfg, logger):
  cfg['abs_pdf_file'] = os.path.join(cfg['abs_dest_dir'],
                                     cfg['pdf_file'])
  shutil.copy(cfg['cropped_pdf_file'], cfg['abs_pdf_file'])

def do_svg(cfg, logger):
  cfg['svg_file'] = cfg['prefix'] + ".svg"
  command = "%(pdf2svg)s %(cropped_pdf_file)s %(svg_file)s" % cfg
  logger.info("running: %s", command)
  subprocess.call(command.split(),
                  stdout=cfg['out_log_file'],
                  stderr=cfg['err_log_file'])
  shutil.copy(cfg['svg_file'], cfg['abs_dest_dir'])

def do_png(cfg, logger):
  cfg['png_file'] = cfg['prefix'] + ".png"
  if cfg['raster_antialias']:
    cfg['antialias_flag'] = "-antialias"
  else:
    cfg['antialias_flag'] = ""
  command = """
            %(convert)s -density %(raster_density)s
                        -trim %(cropped_pdf_file)s
                        -quality %(raster_quality)s
                        %(antialias_flag)s
                        %(png_file)s
            """ % cfg
  command = " ".join(command.split())
  logger.info("running: %s", command)
  subprocess.call(command.split(),
                  stdout=cfg['out_log_file'],
                  stderr=cfg['err_log_file'])
  shutil.copy(cfg['png_file'], cfg['abs_dest_dir'])

OUTPUTS = {'pdf' : do_pdf, 'png' : do_png, 'svg' : do_svg}

def chemfigit(config):
  program = "chemfigit"

  cfg = config.copy()

  # setup logger
  logger = logging.getLogger(program)
  log_level = getattr(logging, cfg['log_level'])
  logger.setLevel(log_level)
  ch = logging.StreamHandler()
  ch.setLevel(log_level)
  formatter = logging.Formatter("%(name)s [%(levelname)s] %(message)s")
  ch.setFormatter(formatter)
  logger.addHandler(ch)

  # setup paths
  cfg['cwd'] = os.getcwd()
  cfg['start_time'] = time.time()
  cfg['temp_base'] = str(cfg['start_time'])
  cfg['temp_dir'] = os.path.join(tempfile.gettempdir(),
                                 program,
                                 cfg['temp_base'])
  cfg['abs_dest_dir'] = os.path.abspath(cfg['dest_dir'])
  cfg['abs_tex_file'] = os.path.abspath(cfg['tex_file'])
  cfg['tex_base'] = os.path.basename(cfg['tex_file'])
  cfg['prefix'] = cfg['tex_base'].rsplit(".", 1)[0]
  cfg['full_pdf_file'] = cfg['prefix'] + ".pdf"

  # create temp dir
  if os.path.exists(cfg['temp_dir']):
    logger.info('Had md5 collision (%s)!', cfg['temp_base'])
    shutil.rmtree(cfg['temp_dir']) # had md5 collision!
  logger.info('Making directory: %s', cfg['temp_dir'])
  os.makedirs(cfg['temp_dir'])

  # create dest dir
  if not os.path.exists(cfg['abs_dest_dir']):
    logger.info('Making directory: %s', cfg['abs_dest_dir'])
    os.makedirs(cfg['abs_dest_dir'])
  
  # do preamble
  if cfg['preamble'] is not None:
    with open(cfg['preamble']) as f:
      original_preamble_text = f.read()
    cfg['preamble_base'] = os.path.basename(cfg['preamble'])
    new_preamble_text = process_includes(cfg, original_preamble_text)
    new_preamble_file = os.path.join(cfg['temp_dir'],
                                     cfg['preamble_base'])
    with open(new_preamble_file, "w") as f:
      f.write(new_preamble_text)

  # copy the tex file
  logger.info("copying %s to %s", cfg['abs_tex_file'],
                                  cfg['temp_dir'])
  shutil.copy(cfg['abs_tex_file'], cfg['temp_dir'])

  # change to the temp dir
  logger.info("Changing dir to %s", cfg['temp_dir'])
  os.chdir(cfg['temp_dir'])

  # create the document file
  cfg['geometry'] = ",".join(["paperwidth=%(paperwidth)s",
                              "paperheight=%(paperheight)s",
                              "margin=%(margin)s"]) % cfg
  doc_setup = r"""
               \documentclass[letter,%(font_size)spt]{article}
               \usepackage[%(geometry)s]{geometry}
               \pagestyle{empty}

               \input{%(preamble_base)s}

               \begin{document}
               \input{%(tex_base)s}
               \end{document}
               """
  cfg['doc_setup'] = textwrap.dedent(doc_setup)[1:] % cfg

  cfg['document_prefix'] = cfg['prefix'] + "-document"
  cfg['tex_document'] = cfg['document_prefix'] + ".tex"

  with open(cfg['tex_document'], "w") as f:
    f.write(cfg['doc_setup'])

  # open log files
  cfg['out_log_file'] = open("stdout.log", "w")
  cfg['err_log_file'] = open("stderr.log", "w")

  # run pdflatex
  pdflatex_command = "%(pdflatex)s %(tex_document)s" % cfg
  logger.info('running 1st time: %s', pdflatex_command)
  subprocess.call(pdflatex_command.split(),
                  stdout=cfg['out_log_file'],
                  stderr=cfg['err_log_file'])
  logger.info('running 2nd time: %s', pdflatex_command)
  subprocess.call(pdflatex_command.split(),
                  stdout=cfg['out_log_file'],
                  stderr=cfg['err_log_file'])

  # crop the pdf
  cfg['pdf_file'] = "%(prefix)s.pdf" % cfg
  cfg['document_pdf'] = cfg['document_prefix'] + ".pdf"
  cfg['cropped_pdf_file'] = "%(prefix)s-crop.pdf" % cfg
  pdfcrop_command = "%(pdfcrop)s %(document_pdf)s %(cropped_pdf_file)s"
  pdfcrop_command = pdfcrop_command % cfg
  logger.info('running: %s', pdfcrop_command)
  subprocess.call(pdfcrop_command.split(),
                  stdout=cfg['out_log_file'],
                  stderr=cfg['err_log_file'])

  # do the outputs
  for output in cfg['output_formats']:
    OUTPUTS[output](cfg, logger)

  # close log files
  cfg['out_log_file'].close()
  cfg['err_log_file'].close()

  # return to cwd
  os.chdir(cfg['cwd'])

  return cfg

def _chemfigit():
  spec = phyles.package_spec(phyles.Undefined, "chemfigit",
                             "schema", "chemfigit.yml")
  converters = {"output_formats": output_formats,
                "optional_file": optional_file}
  setup = phyles.set_up("chemfigit", __version__, spec, converters)
  phyles.run_main(chemfigit, setup['config'], catchall=ChemFigitError)
