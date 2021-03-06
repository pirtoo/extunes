#!/usr/bin/env python3

###########################################################################
# extunes.py v0.20.
# Copyright 2012-2017 Peter Radcliffe <pir-code@pir.net>.
# http://www.pir.net/pir/hacks/extunes.py
#
# Changelist:
# 0.16: cleaned up fat32_convert and used it on playlist filenames too.
# 0.17: removed extraneous progress print conditional.
#       changed progress to print every 100 files.
#       fixed bugs introduced by removing too many characters.
# 0.18: switched name_convert to using urlparse.urlsplit to get a directory
# 0.19: added some playlist handling options, --plist-noclean and
#       --plist-backlslash
# 0.20: fixed typo in help output. Moved not changing playlist content
#       to it's own option, --plist-nomunge.
#       Added the --plist-extm3u option to start playlist files with the
#       line "#EXTM3U".
#       Added the --tracklist option to output a list of tracks in playlist
#       to a file.
#       Added the --nolowercase option to not lowercase filenames in
#       playlists, in case you're syncing files outside this script and
#       to a destinattion filesystem that doesn't remove case.
# 0.21: removed nomunge option from preventing fat32 rewrites entirely
#       to keep path rewrites.
#       Replaced print with print() statements for python3 compatability.
#       Fixed urllib references to work with python 2 or 3.
#
###########################################################################
# Export iTunes(TM) playlists from the XML file and sync a set of
# playlists and their file contents to a destination under the
# sub-directories 'Music' and 'Playlists'.
#
# Playlist files get re-created every time but doesn't copy music files
# if they already exist and are the same size.
#
# If files or playlists are removed from the synced list then they
# are cleaned up and empty directories are removed.
#
# Ignores the existence of non-local tracks (those without a size) which
# are streaming URLs and such.
#
# Tested with Python 2.6 and 2.7 on OSX.
# Requires plistlib which is included with Python 2.6 or later.
# This may work for earlier versions of Python:
#   http://svn.python.org/projects/python/trunk/Lib/plistlib.py
# argparse shipped with Python 2.7 or later, on OSX 10.6.* run:
#   sudo /usr/bin/easy_install-2.6 argparse
#   sudo chmod -R a+rX /Library/Python/2.6/site-packages
# or install newer python with macports, etc.
#
# 0.21 tested with Python 3.7.2 on OSX.
#
# WARNING: will remove anything under the music and playlists
# directories that it isn't syncing on this run!
#
############################################################################

import argparse
import copy
import os
import plistlib
import re
import shutil
import sys
import traceback

try:
    from urlparse import urlsplit
    from urllib import unquote
except ImportError:
    from urllib.parse import urlsplit
    from urllib.parse import unquote

###########################################################################
# Convert a number of bytes into something human readable.
# Taken from: http://goo.gl/zeJZl
def bytes2human(n, format='%(value).4g%(symbol)s'):
  symbols = ('B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
  prefix = {}
  for i, s in enumerate(symbols[1:]):
    prefix[s] = 1 << (i+1)*10
  for symbol in reversed(symbols[1:]):
    if n >= prefix[symbol]:
      value = float(n) / prefix[symbol]
      return format % locals()
  return format % dict(symbol=symbols[0], value=n)

###########################################################################
# Convert local filename to a fat32 valid filename relative to playlist.
# This is rather more restrictive than it needs to be, to be safer/simpler.
#
# If we don't lower case it we can have problems with multi-disk
# albums where the case of the directory is different between iTunes
# sets. Simpler to just lowercase everything, id3 tags will still be
# correct.
def fat32_convert(filename, oldbase=None, newbase=os.sep):

  # If we have a directory prefix to remove, remove it.
  if oldbase is not None:
    filename = filename.split(oldbase)[1]

  if not FLAGS.nolowercase:
    filename = filename.lower()

  if not FLAGS.plist_nomunge:
    # Make sure whatever local filesystem we have the seperator is removed.
    ## -- Can't do this, breaks paths.
    #filename = re.sub('[%s]' % os.sep, '-', filename)
    # Also get rid of multiple runs of spaces, confuses some systems.
    filename = re.sub(' +', ' ', filename)
    # Final cleanup of non-fat32 chars.
    filename = re.sub('[^-_.&%%#@a-zA-Z0-9:\\/%s ]' % os.sep, '-', filename)

  return os.path.join(newbase, filename)


###########################################################################
# Format a list of strings to be quoted and comma seperated.
def quote_list(text_list):
  if not text_list:
    return ''
  return '\'' + '\', \''.join(text_list) + '\''

###########################################################################
# Check if destination directory and its parents up to stopdir exist.
# Recursive function.
def mk_missing_dirs(direct, stopdir):
  if direct != stopdir and not os.path.isdir(direct):
    mk_missing_dirs(os.path.dirname(direct), stopdir)
    #print('Making directory %s' % direct)
    try:
      os.mkdir(direct)
    except (IOError, OSError) as e:
      error_exit('Failed to create directory "%s":\n  %s' %
                 (full_file, e), code=6)

###########################################################################
# Make directories from a list.
def mkdirs(dirs):
  for path in dirs:
    if not os.path.isdir(path):
      if FLAGS.noop and not FLAGS.quiet:
          print('  noop: not creating "%s".' % path)
      else:
        if not FLAGS.quiet:
          print('  Creating "%s".' % path)
        try:
          os.mkdir(path)
        except (IOError, OSError) as e:
          error_exit('Failed to create directory "%s":\n  %s' %
                     (path, e), code=6)

###########################################################################
def clean_tree(base, keep_list):
  # Remove files that are not in keep_list and also any empty
  # directories. Do not remove base.
  file_count = 0
  dir_count = 0

  for root, dirs, files in os.walk(base, topdown=False):
    # python doesn't copy objects and if we delete from the list we're
    # iterating over it loses its place.
    check_files = copy.copy(files)
    for file in check_files:
      full_file = os.path.join(root, file)

      # if the file isn't in the list, delete it.
      if full_file not in keep_list:
        if not FLAGS.quiet:
          print('  Deleting file "%s"' % full_file)
        file_count += 1
        files.remove(file)
        try:
          os.remove(full_file)
        except (IOError, OSError) as e:
          error_exit('Failed to delete file "%s":\n  %s' %
                     (full_file, e), 6)

    # Do not remove the base directory.
    if root is base:
      continue

    if len(files) == 0:
      # dirs is generated before we get here so we may still have
      # directories in the list that have already been deleted
      # check that they still exist and continue out the for loop
      # if any do.
      empty = True
      for adir in dirs:
        if os.path.isdir(os.path.join(root, adir)):
          empty = False
          break
      if not empty:
        continue

      if not FLAGS.quiet:
        print('  Deleting directory "%s"' % root)
      dir_count += 1      
      try:
        os.rmdir(root)
      except (IOError, OSError) as e:
        error_exit('Failed to delete directory "%s":\n  %s' %
                   (full_file, e), code=6)

  return (file_count, dir_count)

###########################################################################
# Print an error to stderr and exit with exit code if one is given.
def error_exit(text, code=None):
  sys.stderr.write(sys.argv[0] + ': ' + text + '\n')
  if code:
    sys.exit(code)

###########################################################################
# Return the last line of a traceback.
def trace_last():
  return traceback.format_exception(sys.exc_info()[0], sys.exc_info()[1],
                                    sys.exc_info()[2])[-1]

###########################################################################
class tunes_xml:
  """Parse an iTunes(TM) XML file and provide easy access to its data."""

  #for entry in self.tunes:
  #  print entry
  #
  # Major Version
  # Minor Version
  # Playlists
  # Features
  # Library Persistent ID
  # Music Folder
  # Application Version
  # Tracks
  # Date

  # Dict entries in playlists and what to flag them as in list mode.
  playlist_flagset = (
    [u'Master', 'A'],
    [u'Music', 'M'],
    [u'Visible', 'N'],
    [u'Movies', 'V'],
    [u'TV Shows', 'T'],
    [u'Purchased Music', 'P'],
    [u'Party Shuffle', 'D'],
    [u'Smart Criteria', 'S'],
  )

  def __init__(self, xmlfile, types=None, all_types=False, video=False):
    # Init and parse the XML.
    try:
      f = open(xmlfile, 'rb')
    except IOError as e:
      error_exit('Cannot open "%s": %s' % (FLAGS.itunes, e), code=4)
    except:
      # Yes, yes, this should raise a new exception. Don't care.
      error_exit('Failed to open iTunes XML file "%s":\n  %s' %
                 (FLAGS.itunes, trace_last()), code=4)

    try:
      if sys.version_info[0] == 3:
        self.tunes = plistlib.load(f)
      else:
        self.tunes = plistlib.readPlist(f)
    except IOError as e:
      error_exit('Cannot open "%s": %s' % (FLAGS.itunes, e), code=4)
    except:
      # Yes, yes, this should raise a new exception. Don't care.
      error_exit('Failed to parse iTunes XML file "%s":\n  %s' %
                 (FLAGS.itunes, trace_last()), code=4)

    f.close()

    # Store what type(s) of files to use.
    if types is None:
      self.types = ['mp2','mp3']
    else:
      self.types = types
    self.all_types = all_types
    self.video = video

    # Create an index to all playlist objects.
    self.plist_index = {}
    for plist_obj in self.__key(u'Playlists'):
      if u'Name' in plist_obj:
        self.plist_index[plist_obj[u'Name']] = plist_obj

  def __has_key(self, key):
    # Return a key from the tunes xml.
    return (key in self.tunes)

  def __key(self, key):
    # Return a key from the tunes xml.
    if not key in self.tunes:
      error_exit('Key "%s" missing from iTunes XML data.'
                 ' Corrupt or newer format?' % key, code=4)
    return self.tunes[key]

  def playlists(self):
    # Return a sorted list of playlist names.
    return sorted(self.plist_index)

  def is_playlist(self, plist_name):
    # Return if a specific playlist name exists or not.
    return (plist_name in self.plist_index)

  def __playlist_obj(self, plist_name):
    # Return a specific playlist object if it exists.
    if plist_name in self.plist_index:
      return self.plist_index[plist_name]
    return None

  def playlist_flags(self, plist_name):
    # Return flags denoting things about a playlist, such as if it is
    # a smart playlist.
    plist = self.__playlist_obj(plist_name)
    if not plist:
      return None
    flags = ''
    for flag in self.playlist_flagset:
      if flag[0] in plist:
        flags += flag[1]
    return flags

  def playlist_tracks(self, plist_name):
    # Return tracks from a playlist in a usable form.
    plist_obj = self.__playlist_obj(plist_name)
    if not plist_obj:
      return None
    tracks = []
    if u'Playlist Items' in plist_obj:
      for track_gobj in plist_obj[u'Playlist Items']:
        if u'Track ID' in track_gobj:
          track = str(track_gobj[u'Track ID'])
          if self.__track_ok(track):
            tracks.append(track)
    return tracks

  def __track_ok(self, track):
    # Return if a track is ok to output or not.
    track_obj = self.__track_obj(track)

    # If we don't know where the track is or what it is we can't do
    # anything with it.
    if not u'Location' in track_obj:
      return False
    if not u'Kind' in track_obj:
      return False
    # if it's protected then we can't play it outside of iTunes.
    if u'Protected' in track_obj:
      return False
    # If the track has no size then it isn't local.
    if not u'Size' in track_obj:
      return False

    # If we are not exporting video files, ignore them.
    if not self.video:
      # AAC audio file
      # AIFF audio file
      # Apple Lossless audio file
      # MPEG audio file
      # MPEG audio stream
      # Protected AAC audio file
      # Protected MPEG-4 video file
      # Purchased AAC audio file
      # Purchased MPEG-4 video file
      # QuickTime movie file
      # WAV audio file
      kind = track_obj[u'Kind'].lower()
      if ' video ' in kind:
        return False
      if ' movie ' in kind:
        return False

    # Are we exporting all types?
    if not self.all_types:
      # If the track isn't of a type we want, ignore it.
      if self.track_suffix(track) not in self.types:
        return False

    return True

  def __track_obj(self, track):
    # Take a track id and return a track object.
    try:
      return self.tunes[u'Tracks'][track]
    except:
      error_exit('Failed to use iTunes XML data for track "%s": %s' %
                 (track, trace_last()), code=4)

  def track_size(self, track):
    # Convert a track id to a track size in bytes.
    if self.__track_ok(track):
      track_obj = self.__track_obj(track)
      try:
        result = track_obj[u'Size']
      except:
        error_exit('Failed to use iTunes XML data for track "%s": %s' %
                   (track, trace_last()), code=4)
      return result
    else:
      return 0

  def name_convert(self, filename):
    # Pull the path section out of a returned URL. Assume it is local
    # because the rest of the script won't work otherwise.
    return unquote(urlsplit(filename)[2])

  def track_name(self, track):
    # Convert a string track id to a local filename.
    try:
      result = self.__track_obj(track)[u'Location']
    except:
      error_exit('Failed to use iTunes XML data for track "%s": %s' %
                 (track, trace_last()), code=4)
    return self.name_convert(result)

  def track_suffix(self, track):
    # Convert a string track id to a local filename suffix.
    name = self.track_name(track)
    suffix = name.split('.')[-1]
    if suffix is name:
      return ''
    return suffix.lower()

  def tracks(self):
    # Return a list of global track ids.
    if not self.__has_key(u'Tracks'):
      return []
    tracks = []
    for track in self.__key(u'Tracks'):
      track = str(track)
      track_gobj = self.__key(u'Tracks')[track]
      if u'Track ID' in track_gobj:
        if self.__track_ok(track):
          tracks.append(track)
    return tracks

  def music_folder(self):
    # Return a converted music folder name.
    return self.name_convert(self.__key(u'Music Folder'))

  def date(self):
    # Return the date of the generated XML.
    return self.__key(u'Date')

  def version(self):
    # Return the version number of the generated XML.
    return '%s.%s' % (self.__key(u'Major Version'),
                      self.__key(u'Minor Version'))

###########################################################################
def main():
  ## TODO(pir):

  ## add command line options:
  ##   paths to be ignored in cleanup under music and playlists

  ## Count how many deletions would be made on a dry run.
  ## - calculate deletions/additions by number of files in list
  ##   vs. number of files in destination?
  ## - return size of files to be deleted?

  ## Generate a list of local files and a list of to be synced files
  ## and diff, rather than going through the filesystem?


  # Command line arguments.
  args = argparse.ArgumentParser(
     description='Export playlists and tracks from iTunes(TM).',
     fromfile_prefix_chars='@',
     epilog='An option of @filename will interpret arguments from '
            'filename, one per line.')

  args.add_argument('--itunes', '-i',
                    help='Location of iTunes XML file',
                    metavar='ITUNES-XML-FILE',
                    default='~/Music/iTunes/iTunes Library.xml')
  args.add_argument('--plistdir',
                    help='Name of playlist directory under destination dir',
                    metavar='PLAYLISTS',
                    default='Playlists')
  args.add_argument('--music',
                    help='Name of music directory under destination dir',
                    default='Music')
  args.add_argument('--quiet', '-q',
                    action='store_true',
                    default=False,
                    help='Quiet file copying/deleting output')
  args.add_argument('--progress', '-#',
                    action='store_true',
                    default=False,
                    help='When in quiet mode print a progress bar of one'
                         ' character per copy of 100 files')
  args.add_argument('--noop', '-n',
                    action='store_true',
                    help='No-op, no operation, dry run')
  args.add_argument('--dest', '-d',
                    help='Destination directory')
  args.add_argument('--list', '-l',
                    action='store_true',
                    help='List playlists found in the XML')
  args.add_argument('--video',
                    action='store_true',
                    default=False,
                    help='Also export video files, still limited by --types')
  args.add_argument('--plists-ignore',
                    nargs='+',
                    default=[],
                    metavar='PLAYLIST',
                    help='List of names of playlists to never export')
  args.add_argument('--plists-prefix',
                    metavar='PREFIX',
                    default='',
                    help='Prefix to add to the start of the playlist names')
  args.add_argument('--plists-noclean',
                    action='store_true',
                    default=False,
                    help='Do not clean up the Playlist directory')
  args.add_argument('--plists-backslash',
                    action='store_true',
                    default=False,
                    help='Use blackslash as the seperator in playlists')
  args.add_argument('--plist-nomunge',
                    action='store_true',
                    default=False,
                    help='Do not rewrite names for tracks in playlists.'
                    ' Used to generate playlist files for existing'
                    ' tracks')
  args.add_argument('--plist-norebase',
                    action='store_true',
                    default=False,
                    help='Do not rebase the track names in playlists.'
                    ' Used to generate playlist files for existing'
                    ' tracks with the full path of the file')
  args.add_argument('--plist-extm3u',
                    action='store_true',
                    default=False,
                    help='Add "#EXTM3U" to the start of playlist files.'
                    ' Helps some devices detect playlist type')
  args.add_argument('--tracklist',
                    metavar='LISTFILE',
                    default='',
                    help='Store the list of track filenames in all playlists'
                    ' to a file given to this option')
  args.add_argument('--nolowercase',
                    action='store_true',
                    default=False,
                    help="Don't lower case filenames in playlists")
  
  arg_copy = args.add_mutually_exclusive_group()
  arg_copy.add_argument('--force',
                        action='store_true',
                        default=False,
                        help='Force tracks to be copied even if they already'
                             ' exist and are the same size.')
  arg_copy.add_argument('--nocopy',
                        action='store_true',
                        default=False,
                        help='Do not copy files for playlists.'
                             ' Used to generate playlist files for existing'
                             ' tracks')

  arg_plists = args.add_mutually_exclusive_group()
  arg_plists.add_argument('--plists', '-p',
                          nargs='+',
                          default=[],
                          metavar='PLAYLIST',
                          help='List of names of playlists to export')
  arg_plists.add_argument('--all-plists', '-a',
                          action='store_true',
                          default=False,
                          help='Export all playlists')

  arg_type = args.add_mutually_exclusive_group()
  arg_type.add_argument('--types',
                        nargs='+',
                        help='What filetype(s) (file extension(s)) of files'
                             ' to export such as mp2, mp3, wav, etc')
  arg_type.add_argument('--all-types',
                        action='store_true',
                        default=False,
                        help='Export all types of (audio, by default) file')


  global FLAGS
  ## Put a try around this to catch @filename errors?
  FLAGS = args.parse_args()

  # If the list option has been given then list playlists and exit.
  if FLAGS.list:
    if not FLAGS.quiet:
      print('Parsing XML file for local file types.')
    itxml = tunes_xml(os.path.expanduser(FLAGS.itunes), types=FLAGS.types,
                      all_types=FLAGS.all_types, video=FLAGS.video)
    print('Playlists found:')
    for plist in itxml.playlists():
      qname = '\'%s\'' % plist
      size = 0
      for track in itxml.playlist_tracks(plist):
        size += itxml.track_size(track)
      print('  %-43s %8d tracks %10s %6s' %
             (qname, len(itxml.playlist_tracks(plist)), bytes2human(size),
             itxml.playlist_flags(plist)))
    sys.exit(0)

  # Arguments that are required if list wasn't given.
  if not FLAGS.dest:
    args.error('one of the arguments --dest/-d --list/-l is required')
  if len(FLAGS.plists) == 0 and not FLAGS.all_plists:
    args.error('one of the arguments --plists/-p --all-plists/-a is required')

  if FLAGS.noop:
    print('noop: No-op mode, no changes will be made!')
  elif FLAGS.force:
    print('force: files will be copied even if they already exist.')

  dest = os.path.expanduser(FLAGS.dest)
  # Error out if the detination doesn't exist.
  if not os.path.isdir(dest):
    args.error('Destination directory not found: "%s"' % dest)
  music = os.path.join(dest, FLAGS.music)
  plist_dir = os.path.join(dest, FLAGS.plistdir)
  if not FLAGS.quiet:
    print('  Music var: %s' % music)
    print('  plist dir: %s' % plist_dir)

  # Make sure playlists and music directories exist.
  if not FLAGS.quiet:
    print('Checking music and playlist paths for existence.')
  if FLAGS.nocopy:
    mkdirs([plist_dir])
  else:
    mkdirs([plist_dir, music])

  # Try to parse the XML file.
  if not FLAGS.quiet:
    print('Parsing XML file for local file types.')
  itxml = tunes_xml(os.path.expanduser(FLAGS.itunes), types=FLAGS.types,
                    all_types=FLAGS.all_types, video=FLAGS.video)
  musicdir = itxml.music_folder()

  if not FLAGS.quiet:
    dbdate = itxml.date()
    dbver = itxml.version()
    print('XML file version %s, date %s' % (dbver, dbdate))
    print('Music dir: %s' % musicdir)
    print('Number of tracks in the db: %d\n' % len(itxml.tracks()))

  # Go through all the possible playlists and match against the
  # ones we want to export that aren't empty and aren't being ignored.
  playlists = []
  ignored_playlists = []
  for plist in itxml.playlists():
    # If we have a match, copy the lists.
    if plist in FLAGS.plists_ignore:
      #if not FLAGS.quiet:
      #  print('Playlist in --plist-ignore: %s' % plist)
      ignored_playlists.append(plist)

    # If we're not ignoring the playlist check if we want it.
    elif FLAGS.all_plists or plist in FLAGS.plists:
      if len(itxml.playlist_tracks(plist)) == 0:
        #if not FLAGS.quiet:
        #  print('Ignoring empty playlist: %s' % plist)
        ignored_playlists.append(plist)
      else:
        playlists.append(plist)

  # Take the list of matching found playlists and remove it from the
  # list of desired playlists to display the missing playlists.
  if FLAGS.all_plists:
    missing_playlists = []
  else:
    missing_playlists = copy.copy(FLAGS.plists)
    for plist in playlists:
      missing_playlists.remove(plist)

  print('Playlist(s) to be copied: %s' % quote_list(playlists))
  if missing_playlists:
    print('Playlist(s) not found: %s' % quote_list(missing_playlists))
  if ignored_playlists:
    print('Playlist(s) ignored: %s' % quote_list(ignored_playlists))

  if FLAGS.noop:
    print('noop: not creating playlists.')
  else:
    if not FLAGS.quiet:
      print('Creating playlists.')

    # Generate a unique list of all track ids required from all playlists
    # that are to be copied.
    # Also keep track of what playlist files we create.
    tracks = []
    playlist_files = []
    for plist in playlists:
      # Add the tracks from this playlist to the general list, keeping it
      # unique with a set conversion.
      plist_tracks = itxml.playlist_tracks(plist)
      tracks = list(set(tracks + plist_tracks))
      # Remove any bad characters that can't be used in filenames.
      plist_filename = fat32_convert('%s%s.m3u' % (FLAGS.plists_prefix,
                                                   plist),
                                                   newbase=plist_dir)

      # Keep a list of all playlist filenames.
      playlist_files.append(plist_filename)

      # Create playlist file.
      if FLAGS.noop and not FLAGS.quiet:
        print('noop: not writing to "%s"' % plist_filename)
      else:
        if not FLAGS.quiet:
          print('  Writing to "%s"' % plist_filename)
        # Try to write the m3u playlist file out.
        try:
          # Opening existing files with 'w' on fat32 devices fails on osx.
          if os.path.exists(plist_filename):
            os.remove(plist_filename)
          plist_file = open(plist_filename, 'w')
        except (IOError, OSError) as e:
          error_exit('Failed to open new playlist "%s":\n   %s' %
                     (plist_filename, e), code=6)

        # Write out the #EXTM3U line to help some players identify
        # the playlist type, if the option is on.
        if FLAGS.plist_extm3u:
          plist_file.write('#EXTM3U\n')
        
        for track in plist_tracks:
          # As well as filename rewriting these paths need to be relative
          # to the playlists directory and DOS style paths with backslashes
          # rather than slashes.
          track_name = itxml.track_name(track)
          track_name = fat32_convert(track_name, oldbase=musicdir,
                                     newbase=music)
          if not FLAGS.plist_norebase:
            track_name = os.path.relpath(track_name, plist_dir)
          if FLAGS.plists_backslash and os.sep != '\\':
            track_name = track_name.replace(os.sep, '\\')

          plist_file.write('%s\n' % track_name)
        plist_file.close()
    print('Number of tracks in desired playlists: %d' % len(tracks))

  if FLAGS.noop:
    print('noop: not cleaning up old playlists.')
  elif FLAGS.plists_noclean:
    print('Not cleaning up old playlists.')
  else:  
    if not FLAGS.quiet:
      print('Cleaning up old playlists.')
    (files, dirs) = clean_tree(plist_dir, playlist_files)
    if not FLAGS.quiet:
      print('  Removed %i files and %i directories.' % (files, dirs))

  if FLAGS.nocopy and FLAGS.tracklist == '':
    # Nothing to check, copy or delete. Don't do anything else.
    sys.exit(0)

  if not FLAGS.quiet:
    synced_size = 0
    for track in tracks:
      # Add up how big the synced size of tracks will be.
      synced_size += itxml.track_size(track)
    print('Size of synced tracks: %s' % bytes2human(synced_size))

    if not FLAGS.nocopy:
      print('Checking tracks.')

  if FLAGS.tracklist != '':
    # We want to write out all track filenames to a file
    print('Writing out list of track filenames to:\n   %s' % FLAGS.tracklist)
    try:
      # Opening existing files with 'w' on fat32 devices fails on osx.
      if os.path.exists(FLAGS.tracklist):
        os.remove(FLAGS.tracklist)
      tracklist_file = open(FLAGS.tracklist, 'w')
    except (IOError, OSError) as e:
      error_exit('Failed to open tracklist "%s":\n   %s' %
                 (FLAGS.tracklist, e), code=6)

  synced_tracks = []
  to_sync_tracks = []
  to_sync_size = 0
  for track in tracks:
    local_file = itxml.track_name(track)
    remote_file = fat32_convert(local_file, oldbase=musicdir, newbase=music)

    if FLAGS.tracklist != '':
      tracklist_file.write('%s\n' % local_file)

    if not FLAGS.nocopy:
      if remote_file in synced_tracks:
        ## We should really add a suffix to the remote name, before the
        ## filetype, and recheck for a collision (increment suffix if
        ## still collides).
        error_exit('WARNING: remote filename collision: "%s"' % remote_file)
      # Append the name to the list of all files in the playlists.
      synced_tracks.append(remote_file)

      # Check if remote file exists already.
      if not FLAGS.force and os.path.isfile(remote_file):
        # If it exists, compare size with os.path.getsize() before copying.
        try:
          local_size = os.path.getsize(local_file)
          remote_size = os.path.getsize(remote_file)
        except (IOError, OSError) as e:
          error_exit('Failed to get filesize: %s' % e)
        else:
          if local_size == remote_size:
            # File exists and is the same size, skip it.
            continue

      # If the file doesn't exist or the filesize doesn't match
      # list the file to be copied.
      to_sync_tracks.append((local_file, remote_file))
      to_sync_size += itxml.track_size(track)

  # finished writing out track names to a file
  tracklist_file.close()

  if FLAGS.nocopy:
    # Nothing to check, copy or delete. Don't do anything else.
    # We only got this far to write out track names.
    sys.exit(0)

  print('Size of tracks to sync: %s' % bytes2human(to_sync_size))

  # Find tracks that are not on the full list and delete them.
  ## Fix clean_tree so it can run in noop.
  if FLAGS.noop:
    print('noop: not checking files and directories to remove.')
  else:
    print('Checking files and directories to remove.')
    (files, dirs) = clean_tree(music, synced_tracks)
    print('  Removed %i file and %i directories.' % (files, dirs))

  # Now that we've freed up whatever disk space can be by deleting things
  # copy any remaining tracks that are needed.
  remaining_tracks = len(to_sync_tracks)
  if remaining_tracks == 0:
    print('No tracks to copy.')
  else:
    if FLAGS.noop:
      print('noop: not copying %i remaining tracks.' % remaining_tracks)
    else:
      print('Copying %i remaining tracks.' % remaining_tracks)

    count = 0
    for (local_file, remote_file) in to_sync_tracks:
      count += 1
      if FLAGS.noop:
        if not FLAGS.quiet:
          print('  noop: not copying "%s"\n   to "%s".' %
                 (local_file, remote_file))
      else:
        if FLAGS.quiet:
          if FLAGS.progress:
            if count % 100 == 0:
              sys.stdout.write('#')
              sys.stdout.flush()
        else:
          print('  Copying "%s"\n   to "%s".' % (local_file, remote_file))

        # Make the full path exist if it doesn't already.
        mk_missing_dirs(os.path.dirname(remote_file), music)
        try:
          ## This copy could be switched to the rsync algorithm?
          shutil.copyfile(local_file, remote_file)
        except (IOError, OSError) as e:
          error_exit('Failed to copy to file "%s":\n  %s' %
                     (remote_file, e), code=6)

    # Print a newline after progress printing above.
    if FLAGS.quiet and FLAGS.progress:
      print()

###########################################################################
if __name__ == '__main__':
  main()

###########################################################################
