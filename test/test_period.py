# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import unittest

import xml.etree.ElementTree as ET
from tinydb import database, Query, storages
from financeager.period import XmlPeriod, TinyDbPeriod
from financeager.model import Model
from financeager.entries import BaseEntry
from financeager.items import CategoryItem
import os

def suite():
    suite = unittest.TestSuite()
    tests = [
            'test_default_name'
            ]
    suite.addTest(unittest.TestSuite(map(CreateEmptyPeriodTestCase, tests)))
    tests = [
            'test_expenses_entry_exists',
            'test_expenses_category_sum'
            ]
    suite.addTest(unittest.TestSuite(map(AddExpenseEntryTestCase, tests)))
    tests = [
            'test_period_name',
            'test_earnings_category_sum',
            'test_expenses_category_sum'
            ]
    suite.addTest(unittest.TestSuite(map(XmlConversionTestCase, tests)))
    suite.addTest(unittest.TestSuite(map(PeriodOnlyXmlConversionTestCase, tests)))
    tests = [
            'test_find_entry',
            'test_remove_entry',
            'test_create_models_query_kwargs',
            'test_repetitive_entries',
            'test_repetitive_quarter_yearly_entries'
            ,'test_category_cache',
            'test_remove_nonexisting_entry'
            ]
    suite.addTest(unittest.TestSuite(map(TinyDbPeriodTestCase, tests)))
    return suite

class CreateEmptyPeriodTestCase(unittest.TestCase):
    def test_default_name(self):
        period = XmlPeriod()
        self.assertEqual(period.name, "2017")

class AddExpenseEntryTestCase(unittest.TestCase):
    def setUp(self):
        self.period = XmlPeriod()
        self.period.add_entry(name="Pineapple", value="-5", category="Fruits")

    def test_expenses_entry_exists(self):
        self.assertIsNotNone(
                self.period._expenses_model.find_name_item(
                    name="Pineapple", category="Fruits"))

    def test_expenses_category_sum(self):
        self.assertAlmostEqual(
                self.period._expenses_model.category_sum("Fruits"),
                5, places=5)

class XmlConversionTestCase(unittest.TestCase):
    def setUp(self):
        earnings_model = Model(name="earnings")
        earnings_model.add_entry(BaseEntry("Paycheck", 456.78))
        expenses_model = Model(name="expenses")
        # expenses_model.add_entry(BaseEntry("Citroën", 24999), category="Car")
        expenses_model.add_entry(BaseEntry("Citroen", 24999), category="Car")
        self.period = XmlPeriod(models=(earnings_model, expenses_model), name="1st Quartal")
        xml_element = self.period.convert_to_xml()
        self.parsed_period = XmlPeriod(xml_element=xml_element)

    def test_period_name(self):
        self.assertEqual(self.parsed_period.name, "1st Quartal")

    def test_earnings_category_sum(self):
        self.assertAlmostEqual(self.parsed_period._earnings_model.category_sum(
            CategoryItem.DEFAULT_NAME), 456.78, places=5)

    def test_expenses_category_sum(self):
        self.assertAlmostEqual(self.parsed_period._expenses_model.category_sum(
            "Car"), 24999, places=5)

class PeriodOnlyXmlConversionTestCase(unittest.TestCase):
    def setUp(self):
        self.period = XmlPeriod(name="1st Quartal")
        self.period.add_entry(name="Paycheck", value=456.78)
        self.period.add_entry(name="Citroen", value="-24999", category="Car")
        xml_element = self.period.convert_to_xml()
        self.parsed_period = XmlPeriod(xml_element=xml_element)

    def test_period_name(self):
        self.assertEqual(self.parsed_period.name, "1st Quartal")

    def test_earnings_category_sum(self):
        self.assertAlmostEqual(self.parsed_period._earnings_model.category_sum(
            CategoryItem.DEFAULT_NAME), 456.78, places=5)

    def test_expenses_category_sum(self):
        self.assertAlmostEqual(self.parsed_period._expenses_model.category_sum(
            "Car"), 24999, places=5)

class TinyDbPeriodTestCase(unittest.TestCase):
    def setUp(self):
        self.period = TinyDbPeriod(name=1901, storage=storages.MemoryStorage)
        self.period.add_entry(name="Bicycle", value=-999.99, date="1901-01-01")

    def test_find_entry(self):
        self.assertIsInstance(self.period.find_entry(name="Bicycle")[0],
                database.Element)

    def test_remove_entry(self):
        response = self.period.remove_entry(category=CategoryItem.DEFAULT_NAME)
        self.assertEqual(0, len(self.period))
        self.assertEqual(1, response["id"])

    def test_create_models_query_kwargs(self):
        self.period.add_entry(name="Xmas gifts", value=500, date="1901-12-23")
        elements = self.period.print_entries(date="1901-12")
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements["elements"][0]["name"], "xmas gifts")

        self.period.add_entry(name="hammer", value=-33, date="1901-12-20")
        elements = self.period.print_entries(name="xmas", date="1901-12")
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements["elements"][0]["name"], "xmas gifts")

    def test_repetitive_entries(self):
        self.period.add_entry(name="rent", value=-500,
                repetitive=["monthly", "1901-10-01"])
        self.assertSetEqual({"standard", "repetitive"}, self.period.tables())

        element = self.period.table("repetitive").all()[0]
        repetitive_elements = list(self.period._create_repetitive_elements(element))
        self.assertEqual(len(repetitive_elements), 3)

        rep_element_names = {e["name"] for e in repetitive_elements}
        self.assertSetEqual(rep_element_names,
                {"rent october", "rent november", "rent december"})

        elements = self.period.print_entries(date="1901-11")
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements["elements"][0]["name"], "rent november")

    def test_repetitive_quarter_yearly_entries(self):
        self.period.add_entry(name="interest", value=25,
                repetitive=["quarter-yearly", "1901-01-01"])

        element = self.period.table("repetitive").all()[0]
        repetitive_elements = list(self.period._create_repetitive_elements(element))
        self.assertEqual(len(repetitive_elements), 4)

        rep_element_names = {e["name"] for e in repetitive_elements}
        self.assertSetEqual(rep_element_names,
                {"interest january", "interest april", "interest july", "interest october"})

        repetitive_table_size = len(self.period.table("repetitive"))
        self.period.remove_entry(name="interest")
        self.assertEqual(len(self.period.table("repetitive")),
                repetitive_table_size - 1)

    def test_category_cache(self):
        self.period.add_entry(name="walmart", value=-50.01,
                category="groceries", date="1901-02-02")
        self.period.add_entry(name="walmart", value=-0.99, date="1901-02-03")

        groceries_elements = self.period.find_entry(category="groceries")
        self.assertEqual(len(groceries_elements), 2)
        self.assertEqual(sum([e["value"] for e in groceries_elements]), -51)

    def test_remove_nonexisting_entry(self):
        response = self.period.remove_entry(name="non-existing")
        self.assertIn("error", list(response.keys()))

    def tearDown(self):
        self.period.close()

if __name__ == '__main__':
    unittest.main()
