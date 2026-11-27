"""Bounded, byte-exact synthetic bundles; local immutable content-addressed objects."""
import hashlib
import os
from pathlib import Path
import re
import tempfile

CHUNK_BYTES=1024*1024
MAX_BYTES=512*1024*1024
MAX_FILES=10000


def require(ok,message):
    if not ok:raise ValueError(message)


def digest(raw):return hashlib.sha256(raw).hexdigest()


def valid_hash(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None


def integer(value,low,high):return type(value) is int and low<=value<=high


def safe_name(value):
    return isinstance(value,str) and len(value)<=240 and all(
        re.fullmatch('[A-Za-z0-9_.-]+',p) and p not in ('.','..') and not p.endswith('.')
        and not re.fullmatch('(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])',p.split('.')[0])
        for p in value.split('/'))


class LocalObjects:
    """Reference create-only store. No overwrite/delete/network API or cloud claims."""
    def __init__(self,root):
        self.root=Path(root)
        require(self.root.is_absolute() and self.root.is_dir() and not self.root.is_symlink(),'existing local object directory required')
        self.root=self.root.resolve()

    def get(self,sha,size):
        require(valid_hash(sha) and integer(size,1,16*1024*1024),'invalid object reference')
        path=self.root/sha
        require(path.is_file() and not path.is_symlink(),'missing or unsafe object')
        with path.open('rb') as stream:raw=stream.read(size+1)
        require(len(raw)==size and digest(raw)==sha,'object hash/size mismatch')
        return raw

    def put(self,raw):
        require(isinstance(raw,bytes) and 0<len(raw)<=16*1024*1024,'invalid object bytes')
        sha=digest(raw);path=self.root/sha
        with tempfile.NamedTemporaryFile(dir=self.root,prefix='.pending-',delete=False) as stream:
            temporary=Path(stream.name)
            try:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            except BaseException:
                stream.close();temporary.unlink();raise
        try:
            try:os.link(temporary,path)
            except FileExistsError:self.get(sha,len(raw))
            if os.name!='nt':
                fd=os.open(self.root,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
        finally:temporary.unlink()
        return dict(sha256=sha,bytes=len(raw))


def validate(bundle):
    require(isinstance(bundle,dict) and bundle.get('schema')=='v9.a6-object-bundle/1','bundle schema')
    chunk=bundle.get('chunk_bytes');files=bundle.get('files')
    require(integer(chunk,1024,16*1024*1024) and isinstance(files,list) and len(files)<=MAX_FILES,'bundle limits')
    names=set();total=0
    for row in files:
        require(isinstance(row,dict) and safe_name(row.get('path')),'unsafe bundle path')
        name=row['path'].casefold()
        require(name not in names and not any(name.startswith(p+'/') or p.startswith(name+'/') for p in names),'duplicate/conflicting bundle path')
        names.add(name)
        size=row.get('bytes');parts=row.get('chunks')
        require(integer(size,0,MAX_BYTES) and valid_hash(row.get('sha256')) and isinstance(parts,list),'file metadata')
        require(len(parts)==(size+chunk-1)//chunk,'chunk inventory')
        for n,part in enumerate(parts):
            require(isinstance(part,dict) and valid_hash(part.get('sha256')) and
                    type(part.get('bytes')) is int and part['bytes']==min(chunk,size-n*chunk),'chunk metadata')
        total+=size;require(total<=MAX_BYTES,'bundle byte limit')
    require(type(bundle.get('bytes')) is int and bundle['bytes']==total,'bundle total')
    return files


def pack(directory,store,*,chunk_bytes=CHUNK_BYTES):
    directory=Path(directory)
    require(directory.is_dir() and not directory.is_symlink(),'regular bundle directory required')
    require(integer(chunk_bytes,1024,16*1024*1024),'chunk limit')
    files=[];total=0
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(),'unsafe bundle file')
        if path.is_dir():continue
        require(path.is_file(),'regular bundle file required')
        name=path.relative_to(directory).as_posix();require(safe_name(name),'unsafe bundle path')
        before=path.stat();total+=before.st_size
        require(total<=MAX_BYTES and len(files)<MAX_FILES,'bundle limit')
        parts=[];hasher=hashlib.sha256();size=0
        with path.open('rb') as stream:
            while True:
                raw=stream.read(chunk_bytes)
                if not raw:break
                size+=len(raw);require(size<=before.st_size,'file changed during packing')
                hasher.update(raw);part=store.put(raw)
                require(part==dict(sha256=digest(raw),bytes=len(raw)),'stored object reference mismatch')
                parts.append(part)
        after=path.stat()
        require(size==before.st_size and (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'file changed during packing')
        files.append(dict(path=name,bytes=size,sha256=hasher.hexdigest(),chunks=parts))
    bundle=dict(schema='v9.a6-object-bundle/1',chunk_bytes=chunk_bytes,bytes=total,files=files)
    validate(bundle)
    return bundle


def chunks(row,store):
    for part in row['chunks']:
        raw=store.get(part['sha256'],part['bytes'])
        # Verify independently of the store adapter, including any future network adapter.
        require(len(raw)==part['bytes'] and digest(raw)==part['sha256'],'returned object mismatch')
        yield raw


def verify(bundle,store):
    """Hash every retained byte without materializing a second file tree."""
    result={}
    for row in validate(bundle):
        hasher=hashlib.sha256()
        for raw in chunks(row,store):hasher.update(raw)
        require(hasher.hexdigest()==row['sha256'],'retained file hash mismatch')
        result[row['path']]=row['sha256']
    return result


def restore(bundle,store,destination):
    files=validate(bundle);destination=Path(destination)
    require(not destination.exists() and not destination.is_symlink(),'new restore directory required')
    destination.mkdir(parents=True)
    for row in files:
        path=destination/row['path'];path.parent.mkdir(parents=True,exist_ok=True)
        hasher=hashlib.sha256()
        with path.open('xb') as stream:
            for raw in chunks(row,store):
                stream.write(raw);hasher.update(raw)
            stream.flush();os.fsync(stream.fileno())
        require(hasher.hexdigest()==row['sha256'],'restored file hash mismatch')
    return destination
