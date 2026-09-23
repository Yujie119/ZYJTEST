from q3_common import *
if __name__=="__main__":
    t=time.perf_counter()
    c=Context()
    print("Q3_PREP_START",c.dem.shape,flush=True)
    prepare_candidates(c)
    print("Q3_CANDIDATES",len(c.qs),flush=True)
    prepare_geometry(c)
    save(OUT/"缓存/预处理资源.json",dict(c.hardware,total_seconds=time.perf_counter()-t,
         dem_bytes=c.dem.nbytes,candidate_count=len(c.qs)))
    print("Q3_PREP_COMPLETE",time.perf_counter()-t,flush=True)

