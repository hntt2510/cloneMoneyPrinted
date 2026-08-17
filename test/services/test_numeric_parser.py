import unittest
from app.services.numeric_parser import (
    CanonicalNumericFact,
    extract_canonical_numeric_facts,
    parse_digit_token,
    parse_spoken_number_phrase,
)


class TestNumericParser(unittest.TestCase):
    def test_spoken_insurance_numbers(self):
        """Verify spoken English numbers in insurance script."""
        # 1. Six thousand dollars
        t1 = "Suppose repairing your car costs six thousand dollars."
        facts1 = extract_canonical_numeric_facts(t1)
        self.assertEqual(len(facts1), 1)
        self.assertEqual(facts1[0].value, 6000.0)
        self.assertTrue(facts1[0].is_currency)
        self.assertEqual(facts1[0].display, "$6,000")

        # 2. One thousand dollars
        t2 = "Your collision deductible is one thousand dollars."
        facts2 = extract_canonical_numeric_facts(t2)
        self.assertEqual(len(facts2), 1)
        self.assertEqual(facts2[0].value, 1000.0)
        self.assertTrue(facts2[0].is_currency)
        self.assertEqual(facts2[0].display, "$1,000")

        # 3. Five thousand dollars
        t3 = "while the insurance company could cover the remaining five thousand dollars,"
        facts3 = extract_canonical_numeric_facts(t3)
        self.assertEqual(len(facts3), 1)
        self.assertEqual(facts3[0].value, 5000.0)
        self.assertTrue(facts3[0].is_currency)
        self.assertEqual(facts3[0].display, "$5,000")

        # 4. Twenty-five thousand dollars
        t4 = "Imagine you have twenty-five thousand dollars of property damage liability coverage,"
        facts4 = extract_canonical_numeric_facts(t4)
        self.assertEqual(len(facts4), 1)
        self.assertEqual(facts4[0].value, 25000.0)
        self.assertTrue(facts4[0].is_currency)
        self.assertEqual(facts4[0].display, "$25,000")

        # 5. Forty thousand dollars
        t5 = "but you cause forty thousand dollars in covered damage."
        facts5 = extract_canonical_numeric_facts(t5)
        self.assertEqual(len(facts5), 1)
        self.assertEqual(facts5[0].value, 40000.0)
        self.assertTrue(facts5[0].is_currency)
        self.assertEqual(facts5[0].display, "$40,000")

    def test_digit_and_k_modifiers(self):
        """Verify digit parsing with $, K, %, and commas."""
        t1 = "$6,000 repair cost and $1,000 deductible"
        facts1 = extract_canonical_numeric_facts(t1)
        self.assertEqual(len(facts1), 2)
        self.assertEqual(facts1[0].value, 6000.0)
        self.assertEqual(facts1[1].value, 1000.0)

        t2 = "$25K coverage limit versus $40,000 damage"
        facts2 = extract_canonical_numeric_facts(t2)
        self.assertEqual(len(facts2), 2)
        self.assertEqual(facts2[0].value, 25000.0)
        self.assertEqual(facts2[1].value, 40000.0)

    def test_spoken_percentages(self):
        """Verify percentage parsing in both word and symbol form."""
        t1 = "Interest rates increased by five percent this year."
        facts1 = extract_canonical_numeric_facts(t1)
        self.assertEqual(len(facts1), 1)
        self.assertEqual(facts1[0].value, 5.0)
        self.assertTrue(facts1[0].is_percent)
        self.assertEqual(facts1[0].display, "5%")

        t2 = "A twenty-five percent discount was applied."
        facts2 = extract_canonical_numeric_facts(t2)
        self.assertEqual(len(facts2), 1)
        self.assertEqual(facts2[0].value, 25.0)
        self.assertTrue(facts2[0].is_percent)

    def test_conversational_phrases_not_misclassified(self):
        """Verify non-quantitative phrases like 'one more number' do not create false facts."""
        t1 = "And there is one more number people often overlook: the coverage limit."
        facts1 = extract_canonical_numeric_facts(t1)
        # 'one' alone without dollar/percent/hundred/thousand is ignored
        self.assertEqual(len(facts1), 0)

    def test_fact_matching(self):
        """Verify CanonicalNumericFact.matches allows format equivalence."""
        spoken_fact = CanonicalNumericFact(value=6000.0, is_currency=True)
        digit_fact = CanonicalNumericFact(value=6000.0, is_currency=False)
        self.assertTrue(spoken_fact.matches(digit_fact))
        self.assertTrue(spoken_fact.matches(6000.0))
        self.assertTrue(spoken_fact.matches(6000))
        self.assertFalse(spoken_fact.matches(5000.0))


if __name__ == "__main__":
    unittest.main()
