from pydub import AudioSegment
from mutagen.easyid3 import EasyID3

from urllib.parse import urlparse, parse_qs
from youtube_dl import YoutubeDL

from queue import Queue
from threading import Thread

import os
import sys
import re
import argparse
import uuid

import splitutil


mdProviders = []
for module in os.listdir("MetaDataProviders"):
    if module == "__init__.py" or module[-3:] != ".py" or module=="splitutil.py":
        continue
    mdProviders.append(__import__("MetaDataProviders." + module[:-3], fromlist=[""]))


class MyLogger(object):
    def debug(self, msg):
        pass
    def warning(self, msg):
        pass
    def error(self, msg):
        print(msg)


def thread_func(album, tracksStarts, queue, FOLDER):
    while not queue.empty():
        song_tuple = queue.get()
        split_song(album, tracksStarts, song_tuple[0], song_tuple[1], FOLDER)


def split_song(album, tracksStarts, index, track, FOLDER):
    print("\t{}) {}".format(str(index+1), track))
    start = tracksStarts[index]
    end = tracksStarts[index+1]
    duration = end-start
    track_path = '{}/{:02d} - {}.mp3'.format(FOLDER, index+1, track)
    album[start:][:duration].export(track_path, format="mp3")

    print("\t\tTagging")
    song = EasyID3(track_path)
    if ARTIST:
            song['artist'] = ARTIST
    if ALBUM:
            song['album'] = ALBUM
    song['title'] = track
    song['tracknumber'] = str(index+1)
    song.save()


def my_hook(d):
    if d['status'] == 'downloading':
        sys.stdout.write('\r\033[K')
        sys.stdout.write('\tDownloading video | ETA: {} seconds'.format(str(d["eta"])))
        sys.stdout.flush()
    elif d['status'] == 'finished':
        sys.stdout.write('\r\033[K')
        sys.stdout.write('\tDownload complete\n\tConverting video to mp3')
        sys.stdout.flush()


# youtube_dl configuration
ydl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': '%(id)s.%(ext)s',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'wav',
        'preferredquality': '0',
    }],
    'logger': MyLogger(),
    'progress_hooks': [my_hook],
}


if __name__ == "__main__":
    print("Starting")

    # arg parsing
    parser = argparse.ArgumentParser(description='Split a single-file mp3 Album into its tracks.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-mp3", help="The .mp3 file you want to split.", metavar="mp3_file")
    group.add_argument("-yt", help="The YouTube video url you want to download and split.", metavar="youtube_url")
    parser.add_argument("-a", "--artist", help="Specify the artist that the mp3s will be ID3-tagged with. Default: no tag", default=None)
    parser.add_argument("-A",  "--album", help="Specify the album that the mp3s will be ID3-tagged with. Default: no tag", default=None)
    parser.add_argument("-t", "--tracks", help="Specify the tracks file. Default: tracks.txt", default="tracks.txt")
    parser.add_argument("-f", "--folder", help="Specify the folder the mp3s will be put in. Default: splits/", default=None)
    parser.add_argument("-d", "--duration", dest='duration', action='store_true', help="Specify track time format will use the duration of each individual song. Default: False", default=False)
    parser.add_argument("-th", "--threaded", dest='threaded', action='store_true', help="Specify the script should use threads. Default: False", default=False)
    parser.add_argument("--num-threads", dest='num_threads', help="Specify the (whole/non-negative) number of threads the script should spawn when using threads. Default: 3", default='3')
    parser.add_argument("--metadata", dest='metadata', help="Specify the source for the Album Metadata.", default="file")
    
    args = parser.parse_args()
    TRACKS_FILE = args.tracks
    FILENAME = args.mp3
    YT_URL = args.yt
    ALBUM = args.album
    ARTIST = args.artist
    DURATION = args.duration
    THREADED = args.threaded
    NUM_THREADS = int(args.num_threads)
    METASRC = args.metadata

    if args.folder is None:
        if ALBUM and ARTIST:
            FOLDER = "{} - {}".format(ARTIST, ALBUM)
        else:
            if YT_URL:
                url_data = urlparse(YT_URL)
                query = parse_qs(url_data.query)
                videoID = query["v"][0]
                FOLDER = "./splits/{}".format(videoID)
            else:
                FOLDER = "./splits/{}".format(str(uuid.uuid4())[:16])
    else:
        FOLDER = args.folder

    # create destination folder
    if not os.path.exists(FOLDER):
        os.makedirs(FOLDER)

    if METASRC != "file":
        found_a_source = False
        for provider in mdProviders:
            pattern = re.compile(provider.VALID_URL)
            if pattern.match(METASRC):
                print("Matched with a metadata provider...")
                if not provider.lookup(METASRC, TRACKS_FILE):
                    print("Can't find a track list in the provided source. Shutting Down.")
                    exit()
                else:
                    found_a_source = True
                    break
        if not found_a_source:
            print("There was no provider able to get data from your source!")
            exit()

    tracksStarts = []
    tracksTitles = []

    regex = re.compile("(?P<start>.+)\s*\-\s*(?P<title>.+)")

    print("Parsing " + TRACKS_FILE)
    with open(TRACKS_FILE) as tracksF:
        if DURATION:
            time_elapsed = '0:00:00'
            for i, line in enumerate(tracksF):
                m = regex.match(line)

                tStart = splitutil.timeToSeconds(time_elapsed)
                tTitle = m.group('title').strip()

                tracksStarts.append(tStart*1000)
                tracksTitles.append(tTitle)

                curr_track_time = m.group('start').strip()
                time_elapsed = splitutil.updateTimeChange(time_elapsed, curr_track_time)
        else:
            for i, line in enumerate(tracksF):
                m = regex.match(line)

                tStart = splitutil.timeToSeconds(m.group('start').strip())
                tTitle = m.group('title').strip()

                tracksStarts.append(tStart*1000)
                tracksTitles.append(tTitle)
    print("Tracks file parsed")

    album = None
    if YT_URL:
        url_data = urlparse(YT_URL)
        query = parse_qs(url_data.query)
        videoID = query["v"][0]
        FILENAME = videoID + ".wav"
        if not os.path.isfile(FILENAME):
                print("Downloading video from YouTube")
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download(['http://www.youtube.com/watch?v=' + videoID])
                print("\nConversion complete")
        else:
                print("Found matching file")
        print("Loading audio file")
        album = AudioSegment.from_file(FILENAME, 'wav')
    else:
        print("Loading audio file")
        album = AudioSegment.from_file(FILENAME, 'mp3')
    print("Audio file loaded")

    tracksStarts.append(len(album))  # we need this for the last track/split

    print("Starting to split")
    if THREADED and NUM_THREADS > 1:
        # Create our queue of indexes and track titles
        queue = Queue()
        for index, track in enumerate(tracksTitles):
            queue.put((index, track))
        # initailize/start threads
        threads = []
        for i in range(NUM_THREADS):
            new_thread = Thread(target=thread_func, args=(album, tracksStarts, queue, FOLDER))
            new_thread.start()
            threads.append(new_thread)
        # wait for them to finish
        for thread in threads:
            thread.join()
    # Non threaded execution
    else:
        tracksTitles.append("END")
        for i, track in enumerate(tracksTitles):
            if i != len(tracksTitles)-1:
                split_song(album, tracksStarts, i, track, FOLDER)
    print("All Done")
