from comicapi.genericmetadata import GenericMetadata
import os
import re
from PIL import Image
from comicapi import comicinfoxml, filenameparser
import tempfile
import shutil
import hashlib
import io
import json
import xml.etree.ElementTree as ET
import fitz # PyMuPDF
import config
import archiveutil

SETTINGS = config.get_config() 

scene_groups = []
metadata_files = []
hashed_files = {}

if os.path.exists("comicutil.json"):
    with open("comicutil.json") as json_text:
        comicutil_json = json.load(json_text)
        if "scene_groups" in comicutil_json:
            scene_groups = comicutil_json["scene_groups"]
        if "metadata_files" in comicutil_json:
            metadata_files = comicutil_json["metadata_files"]
        if "hashed_files" in comicutil_json:
            hashed_files = comicutil_json["hashed_files"]
        


def remove_issue_number(filename):
    name = filename.partition('#')[0]
    return name

def pad_to_length(number,length=3):
    return number.zfill(length)

def stripBadChars(string):
    return string.replace(': ',' - ').replace('/','-').replace('  ',' ').strip()

def getFileExtension(filename):
    return os.path.splitext(filename)

def get_comic_details(name):
    fnp = filenameparser.FileNameParser()
    fnp.parseFilename(name)
    return fnp

def get_series_name(name):
    fnp = filenameparser.FileNameParser()
    fnp.parseFilename(name)
    return fnp.series

def getYearFromName(name):
    #return re.search('\d{4}',name).group()
    return re.findall('\d{4}',name)[-1]

def getYearFromVolume(name):
    try:
        #return re.search('\d{4}',name).group()
        return re.findall('\d{4}',name)[0]
    except:
        return ""

def _get_issue_number(name):
    if "#" in name:
        split = name.split()
        for part in split:
            if "#" in part:
                return re.sub("[^0-9]", "", part)
        return ""
    else:
        return ""

def get_issue_number(issue):
    issue_number = ""
    fnp = filenameparser.FileNameParser()
    fnp.parseFilename(issue)
    issue_number = fnp.issue
    if fnp.issue == "":
        issue_number = _get_issue_number(issue)
    return issue_number

def is_image(file):
    try:
        Image.open(file)
    except IOError:
        return False
    return True

def get_meta_from_dir(dir):
    metas = {"ComicInfo.xml":""}
    for subdir, dirs, files in os.walk(dir):
        for file in files:
            filepath = subdir + os.sep + file
            basename = os.path.basename(filepath)
            if basename != "" and basename in metadata_files:
                if basename == "ComicInfo.xml":
                    meta = comicinfoxml.ComicInfoXml().readFromExternalFile(filepath)
                    metas["ComicInfo.xml"] = meta
    return metas

def remove_hashed_files_from_dir(dir):
    for subdir, dirs, files in os.walk(dir):
        for file in files:
            filepath = subdir + os.sep + file
            with open(filepath,"rb") as f:
                bytes = f.read() # read entire file as bytes
                readable_hash = hashlib.sha256(bytes).hexdigest().upper()
                if readable_hash in hashed_files:
                    print(f"Removing the following known hashed files: {hashed_files[readable_hash]}: {readable_hash}")
                    f.close()
                    os.remove(filepath)

def merge_meta_xml(xml1,xml2,priority):
    xml1 = ET.fromstring(xml1)
    xml2 = ET.fromstring(xml2)

    if priority == "xml1":
        for i in xml1:
            found = xml2.find(i.tag)
            if found != None:
                found.text = i.text
            else:
                xml2.append(i)
        return ET.tostring(xml2, encoding='utf8', method='xml').decode()
    else:
        for i in xml2:
            found = xml1.find(i.tag)
            if found != None:
                found.text = i.text
            else:
                xml1.append(i)
        return ET.tostring(xml1, encoding='utf8', method='xml').decode()

def write_meta_to_dir(metadata,dir,type):
    try:
        if type == "ComicInfo.xml":
            writer = comicinfoxml.ComicInfoXml()
            file = os.path.join(dir,"ComicInfo.xml")
            writer.writeToExternalFile(file,metadata)
            return True
    except:
        return False

def comicdb_to_meta(results):
    metadata = GenericMetadata()
    md  =  metadata
    if "genres" in results:
        md.genre = results["genres"]
    if results["description"] != "":
        md.comments = results["description"]
    if results["page_count"] != "":
        md.pageCount = results["page_count"]
    md.credits = results["credits"]
    md.webLink = results["issueLink"]
    md.title = results["issueName"]
    md.issue = results["issueNumber"]
    md.series = results["name"]
    #md.issueCount = results["issue_count"]
    md.publisher = results["publisher"]
    metadata.isEmpty = False
    return metadata

def get_possible_promos_from_dir(dir):
    promos = []
    totallength = 0
    non_empty_files = []
    for subdir, dirs, files in os.walk(dir):
        for file in files:
            filepath = subdir + os.sep + file
            basename = os.path.basename(filepath)
            if basename != "" and basename not in metadata_files:
                totallength += len(basename)
                non_empty_files.append(basename)
    for file in non_empty_files:
        if len(file) < totallength / len(non_empty_files):
            promos.append(os.path.splitext(file)[0])
    return promos

def remove_promos_from_dir(dir):
    found = False
    promos = []
    try:
        for subdir, dirs, files in os.walk(dir):
            for file in files:
                filepath = subdir + os.sep + file
                base = os.path.basename(filepath)
                if base != "" and os.path.splitext(base)[0] in scene_groups:
                    os.remove(filepath)
                    print(f"Removing promo: {os.path.splitext(base)[0]}")
                    found = True
        if not found:
            print("No scene promos found")
            promos = get_possible_promos_from_dir(dir)   
            print(f"Possible scene promos: {' '.join(map(str,promos))}")  
            return found
        return found
    except Exception as e:
        print(f"Failed to remove promos from directory: {e}")
        return found

def remove_promos_from_file(filename,pdf_zoom):
    tmp = ""
    try:
        tmp = archiveutil.extract_to_temp(filename,pdf_zoom)
    except Exception as e:
        print("Extract error: ",e)
        shutil.rmtree(tmp)
        return False
    promos_found = False
    try:
        promos_found = remove_promos_from_dir(tmp)
    except Exception as e:
        print(f"Error removing promos: {e}")
        shutil.rmtree(tmp)
        return False
    if not promos_found:
        shutil.rmtree(tmp)
        return False
    try:
        return archiveutil.dir_to_archive(tmp,filename)
    except Exception as e:
        print("Archive error: ",e)
        shutil.rmtree(tmp)
        return False

def remove_comixology_meta_from_dir(dir):
    for subdir, dirs, files in os.walk(dir):
        for file in files:
            filepath = subdir + os.sep + file
            base = os.path.basename(filepath)
            if base == ".meta.asc":
                os.remove(filepath)
                print("Removing Comixology meta.asc file")

def get_cover_from_dir(dir):
    cover = ""
    for subdir, dirs, files in os.walk(dir):
        for file in files:
            filepath = subdir + os.sep + file
            if is_image(filepath):
                cover = filepath
                break
    img = Image.open(cover).convert('RGB')
    return img

if __name__ == "__main__":
    print(_get_issue_number("W.E.B. of Spider-Man #1"))