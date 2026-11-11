import copy
import math
import unittest

from detection.collision_policy import FEATURE_NAMES,interaction_features,close_pair
from detection.warnings import WarningEngine
from detection.tests.test_warnings import detection,frame


class CertainPolicy:
    threshold=.8
    metadata={'synthetic_only':True}
    def score(self,features):return 1.


class LearnedCollisionContractTests(unittest.TestCase):
    def sequence(self,ground_truth=False,track=True,moving=True):
        engine=WarningEngine(collision_model=CertainPolicy());alerts=[]
        for i in range(24):
            x=30+min(i,8)*3.75 if moving else 60
            row=frame(i/8,[detection('car',[x,40,x+30,60],1 if track else None),
                            detection('car',[80,40,110,60],2 if track else None)])
            if ground_truth:row.update(scenario={'events':[{'event_type':'vehicle_collision'}]},signals={'vehicle':'red'},objects=[{'fake':'label'}])
            alerts.extend(engine.update(row))
        return alerts

    def test_model_needs_history_and_consecutive_scores_and_latches(self):
        alerts=self.sequence()
        self.assertEqual(len(alerts),1)
        self.assertGreaterEqual(alerts[0]['timestamp'],.75)
        self.assertIn('collision_decision',alerts[0])

    def test_ground_truth_does_not_affect_runtime(self):
        self.assertEqual(self.sequence(),self.sequence(ground_truth=True))

    def test_missing_ids_do_not_invent_vehicle_pairs(self):
        self.assertEqual(self.sequence(track=False),[])

    def test_initially_stationary_cars_cannot_become_collision_from_score_alone(self):
        self.assertEqual(self.sequence(moving=False),[])

    def test_schema_is_finite_and_history_is_causal(self):
        a=detection('car',[20,30,40,50],1);b=detection('car',[35,30,55,50],2)
        engine=WarningEngine();history={'primary:1':[(0,30,50,20),(100,9999,9999,9999)],'primary:2':[(0,45,50,20)]}
        values=interaction_features(a,b,history,engine.key,.2,.2)
        clean=copy.deepcopy(history);clean['primary:1'].pop()
        # The historical base feature function also filters on nonnegative age.
        self.assertEqual(values,interaction_features(a,b,clean,engine.key,.2,.2))
        self.assertEqual(len(values),len(FEATURE_NAMES));self.assertTrue(all(map(math.isfinite,values)))

    def test_geometry_does_not_pair_distant_objects(self):
        self.assertFalse(close_pair(detection(box=[0,0,20,20]),detection(box=[150,0,170,20])))


if __name__=='__main__':unittest.main()
