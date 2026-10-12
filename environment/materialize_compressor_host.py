"""Install the recorded Compressor host into an isolated custom_transformer vendor only."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vendor",type=Path,required=True)
    p.add_argument("--corrected-host",type=Path,required=True)
    a=p.parse_args()
    vendor=a.vendor.resolve()
    assert vendor.name=="custom_transformer", "Never apply this operation to the AFD plugin vendor"
    spec=json.loads((Path(__file__).with_name("versions.json")).read_text())["native"]
    api=vendor/"op_api/lib/libcust_opapi.so"
    host=vendor/"op_impl/ai_core/tbe/op_tiling/lib/linux/aarch64/libcust_opmaster_rt2.0.so"
    digest=lambda b:hashlib.sha256(b).hexdigest()
    api_bytes=api.read_bytes();host_bytes=a.corrected_host.read_bytes()
    assert digest(api_bytes)==spec["compressor_api"]
    assert digest(host_bytes)==spec["compressor_host"]
    backup=vendor/"benchmark-loader-before"
    backup.mkdir(exist_ok=False)
    for name,path in (("api",api),("host",host)):
        shutil.copyfile(path,backup/name)
        (backup/(name+".location.txt")).write_text(str(path.resolve())+"\n")
    for path,data in ((api,api_bytes),(host,host_bytes)):
        if path.is_symlink():
            path.unlink()
        path.write_bytes(data)
    assert api.resolve()==api and host.resolve()==host
    print(json.dumps({"vendor":str(vendor),"api_sha256":digest(api_bytes),
                      "host_sha256":digest(host_bytes),"backup":str(backup)}))

if __name__=="__main__":
    main()
