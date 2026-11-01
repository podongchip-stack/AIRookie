import unittest
from voice_treatments import normalize, TREATMENTS

class TreatmentSummaryTests(unittest.TestCase):
    def test_categories_and_patient_stay_together(self):
        result = normalize({'patient_count': 1, 'patients': [{
            'gender': '남성', 'age_group': '60대', 'cc_minor': '흉통',
            'sbp': 100, 'temp': 36.5, 'treat_categories': list(TREATMENTS),
            'pre_ktas': {'level': 2, 'source': 'rule'}}]})
        self.assertEqual(len(result['treatment']), 28)
        self.assertIn('부목 고정', result['treatment'])
        self.assertEqual(result['vitals'][0]['bt'], 36.5)
        self.assertEqual(result['ktas_level'], 2)
        self.assertEqual(result['patient'], '60대 남성')

    def test_schema_and_dashboard_patient_info(self):
        from schema import VoiceCallSummaryMessage
        from hub_engine import HubEngine
        voice = VoiceCallSummaryMessage.model_validate({
            'caseId': 'case-treatment-test',
            'transcript': {'raw_text': '산소 투여와 부목 고정', 'filtered_text': '산소 투여와 부목 고정'},
            'summary': {'patient_count': 1, 'patients': [{
                'cc_minor': '하지 손상', 'treat_categories': ['oxygen', 'splint'],
                'pre_ktas': {'level': 3, 'source': 'rule'}}]}})
        engine = HubEngine(specialty_matcher=object())
        patient = engine._patient_info(voice)
        self.assertEqual(patient.treatment, ['산소투여', '부목 고정'])
        self.assertEqual(patient.rawTranscript, '산소 투여와 부목 고정')
        self.assertEqual(patient.ktasLevel, 3)

    def test_multiple_patients_are_not_combined(self):
        with self.assertRaises(ValueError):
            normalize({'patient_count': 2, 'patients': [{}, {}]})

    def test_no_treatment_or_ktas_is_invented(self):
        result = normalize({'patient_count': 1, 'patients': [{}]})
        self.assertEqual(result['treatment'], [])
        self.assertIsNone(result['ktas_level'])

if __name__ == '__main__': unittest.main()
