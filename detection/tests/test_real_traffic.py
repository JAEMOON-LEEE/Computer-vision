import numpy as np

from detection.prepare_real_traffic import grouped_splits
from detection.real_incident import scene_hit, vote_scores


def test_transitive_near_duplicate_group_cannot_cross_splits():
    rows=[{"source_id":"a","phash":0},{"source_id":"b","phash":255},
          {"source_id":"c","phash":65535},{"source_id":"d","phash":2**63-1}]
    result=grouped_splits(rows)
    assert len({r["split"] for r in result[:3]})==1
    assert {r["group_id"] for r in result[:3]}=={"a"}
    assert result[-1]["group_id"]=="d"


def test_scene_warning_needs_persistent_observations_not_single_peak_or_cut():
    assert scene_hit([.9,.9,.9],[0,.5,1],.8)
    assert not scene_hit([.9,.4,.9],[0,.5,1],.8)
    assert not scene_hit([.9,.9,.9],[0,.5,2.5],.8)
    assert not scene_hit([.9,.9,.9],[0,.2,.4],.8)
    assert not scene_hit([1,1,1],[0,.5,1],1.001)


def test_opencv_vote_class_order_is_not_assumed():
    class Model:
        def getVotes(self,rows,flags):
            return np.asarray([[1,0],[12,4],[1,15]])
    assert vote_scores(Model(),np.zeros((2,256),np.float32)).tolist()==[.75,.0625]
