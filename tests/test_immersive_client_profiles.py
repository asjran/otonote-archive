import unittest

from tools.build_immersive_client_profiles import bone_partition, make_profile


class ImmersiveClientProfileTests(unittest.TestCase):
    def test_shared_ancestor_is_neutral_and_slot_labels_win(self):
        skeleton = {'bones': [{'name': 'root'}, {'name': 'shared', 'parent': 'root'},
            {'name': 'Alice', 'parent': 'shared'}, {'name': 'Bob', 'parent': 'shared'}],
            'slots': [{'name': 'Alice_back', 'bone': 'Alice'}, {'name': 'Bob_hair', 'bone': 'Bob'},
                      {'name': 'Bob_effect', 'bone': 'Alice'}, {'name': 'table', 'bone': 'root'}]}
        result = bone_partition(skeleton, {'alice': 1, 'bob': 2})
        self.assertEqual(result['bones'], [None, None, 1, 2])
        self.assertEqual(result['slots'], [1, 2, 2, None])

    def test_unnamed_limbs_and_constraint_targets_follow_authored_member_hierarchy(self):
        skeleton = {'bones': [{'name': 'root'}, {'name': 'Alice', 'parent': 'root'},
            {'name': 'hand', 'parent': 'Alice'}, {'name': 'aim', 'parent': 'root'}],
            'slots': [{'name': 'skin', 'bone': 'hand'}],
            'ik': [{'bones': ['hand'], 'target': 'aim'}]}
        self.assertEqual(bone_partition(skeleton, {'alice': 1})['bones'], [None, 1, 1, 1])

    def fixture(self):
        vector = lambda x, y, z: dict(zip('xyz', (x, y, z)))
        settings = {'fieldOfView': 19, 'zoomMinFov': 10, 'zoomMaxFov': 35,
            'originalOffset': vector(0, 0, 1), 'defaultPositionOffset': vector(0, 0, -1),
            'zoomOutStartPosition': vector(0, 0, -2), 'orbitRatio': 1,
            'zoomOutDuration': 1, 'zoomOutEase': 9, 'backgroundPosition': vector(0, 0, 0),
            'backgroundRotation': vector(10, 20, 30), 'backgroundScale': vector(1, 1, 1)}
        components = [{'name': 'settings', 'fields': settings},
            *[{'name': name, 'fields': {'_characterId': cid}} for cid, name in [(1, 'Alice'), (2, 'Bob'), (9, 'Stale')]],
            {'gameObjectId': '10', 'name': 'AliceBob', 'fields': {'_animation': []}}]
        scene = {'nodes': [{'id': '1', 'gameObjectId': '10', 'parent': '0', 'name': 'skeleton', 'spine': 'body'},
            {'id': '2', 'gameObjectId': '20', 'parent': '0', 'name': 'Alice_bag', 'spine': 'bag'},
            {'id': '3', 'gameObjectId': '30', 'parent': '0', 'name': 'bg'}]}
        spot = {'_id': 7, '_characterIds': [1, 2], '_backgroundAssetPath': 'x/bg'}
        labels = {cid: {'name': name, 'nameEn': name, 'tokens': []} for cid, name in [(1, 'Alice'), (2, 'Bob')]}
        return spot, components, scene, labels

    def test_stale_anchors_are_never_relabelled_and_accessories_join_their_member(self):
        profile, shared, ignored = make_profile(*self.fixture())
        self.assertEqual([c['id'] for c in profile['characters']], [1, 2])
        self.assertEqual(profile['characters'][0]['nodes'], ['1', '2'])
        self.assertEqual(profile['characters'][1]['nodes'], ['1'])
        self.assertEqual(shared, {'1': {'alice': 1, 'bob': 2}})
        self.assertEqual(ignored[0]['nativeId'], 9)
        self.assertEqual(profile['camera']['start'], [0, 0, 2])
        self.assertEqual(profile['camera']['end'], [0, 0, 2])

    def test_supporting_actor_keeps_a_web_id_instead_of_the_conflicting_master_id(self):
        spot, components, scene, labels = self.fixture()
        scene['nodes'].append({'id': '4', 'gameObjectId': '40', 'parent': '0', 'name': 'Stale', 'spine': 'extra'})
        extra = {'id': 'scene-stale', 'alias': 'stale', 'name': '配角', 'nameEn': 'Supporting actor'}
        profile, _, warnings = make_profile(spot, components, scene, labels, [extra])
        self.assertEqual(profile['characters'][-1]['id'], 'scene-stale')
        self.assertEqual(profile['characters'][-1]['nodes'], ['4'])
        self.assertEqual(warnings[0]['nativeId'], 9)
        self.assertEqual(warnings[0]['webActorId'], 'scene-stale')
        self.assertNotIn(9, [c['id'] for c in profile['characters']])

    def test_an_unbound_member_fails_instead_of_enabling_an_incomplete_scene(self):
        spot, components, scene, labels = self.fixture()
        components[-1]['name'] = 'Alice'
        with self.assertRaisesRegex(ValueError, 'unbound member'):
            make_profile(spot, components, scene, labels)


if __name__ == '__main__':
    unittest.main()
