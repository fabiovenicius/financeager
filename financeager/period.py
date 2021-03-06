#-*- coding: utf-8 -*-
from __future__ import unicode_literals

import os.path
from collections import defaultdict, Counter
from dateutil import rrule
from datetime import datetime as dt

from PyQt5.QtCore import QDate
import xml.etree.ElementTree as ET
from tinydb import TinyDB, Query, where, JSONStorage
from tinydb.database import Element
from tinydb.queries import QueryImpl

from financeager.model import Model
from financeager.entries import BaseEntry, CategoryEntry
from financeager.items import DateItem, CategoryItem

#FIXME create config singleton
CONFIG_DIR = os.path.expanduser("~/.config/financeager")


class Period(object):

    DEFAULT_NAME = QDate.currentDate().year()

    def __init__(self, name=None):
        self._name = "{}".format(Period.DEFAULT_NAME if name is None else name)

    @property
    def name(self):
        return self._name

class XmlPeriod(Period):

    def __init__(self, name=None, xml_element=None, models=None):
        super(XmlPeriod, self).__init__(name)
        # TODO store models in dict
        self._earnings_model = None
        self._expenses_model = None
        if models is not None and len(models) == 2:
            self._earnings_model, self._expenses_model = models
        elif xml_element is not None:
            self.create_from_xml(xml_element)
        if self._earnings_model is None:
            self._earnings_model = Model(name="earnings")
        if self._expenses_model is None:
            self._expenses_model = Model(name="expenses")

    def create_from_xml(self, xml_element):
        for model_element in xml_element.findall("model"):
            name = model_element.get("name")
            if name == "earnings":
                self._earnings_model = Model(model_element)
            elif name == "expenses":
                self._expenses_model = Model(model_element)
        self._name = xml_element.get("name", Period.DEFAULT_NAME)

    def convert_to_xml(self):
        period_element = ET.Element("period", name=self._name)
        period_element.text = "\n"
        for model_name in ["earnings", "expenses"]:
            model_element = getattr(self,
                    "_{}_model".format(model_name)).convert_to_xml()
            period_element.append(model_element)
        return period_element

    def add_entry(self, **kwargs):
        value = str(kwargs.pop("value"))
        category = kwargs.get("category")
        name = kwargs["name"]
        date = kwargs.get("date")
        if value.startswith("-"):
            self._expenses_model.add_entry(
                    BaseEntry(name, value, date), category=category)
        else:
            self._earnings_model.add_entry(
                    BaseEntry(name, value, date), category=category)

class TinyDbPeriod(TinyDB, Period):

    def __init__(self, name=None, *args, **kwargs):
        """
        Create a period with a TinyDB database backend, identified by ``name``.
        The filepath arg for tinydb.JSONStorage is derived from the name.
        Keyword args other than ``default_table`` (set to ``standard``) are
        passed to the TinyDB constructor (f.i. storage type).
        """

        self._name = "{}".format(Period.DEFAULT_NAME if name is None else name)
        kwargs["default_table"] = "standard"
        if kwargs.get("storage", JSONStorage) == JSONStorage:
            args = list(args) + [os.path.join(CONFIG_DIR, "{}.json".format(self._name))]
        super(TinyDbPeriod, self).__init__(*args, **kwargs)
        self._create_category_cache()

    def _create_category_cache(self):
        """The category cache assigns a counter for each element name in the
        database (excluding repetitive elements), keeping track of the
        categories the element was labeled with. This allows deriving the
        category of an element if not explicitly given."""
        self._category_cache = defaultdict(Counter)
        for element in self.all():
            self._category_cache[element["name"]].update([element["category"]])

    def add_entry(self, **kwargs):
        value = kwargs["value"]
        name = kwargs["name"].lower()
        date = kwargs.get("date")
        if date is None:
            date = str(DateItem())
        category = kwargs.get("category")

        # derive category if not given but unique in cache
        if category is None:
            if len(self._category_cache[name]) == 1:
                category = self._category_cache[name].most_common(1)[0][0]
            else:
                # assign default name (must be str), s.t. category field can be queried
                category = CategoryItem.DEFAULT_NAME
        else:
            category = category.lower()

        self._category_cache[name].update([category])

        repetitive_args = kwargs.get("repetitive", False)
        if repetitive_args:
            frequency = repetitive_args[0].lower()
            start = str(DateItem())
            if len(repetitive_args) > 1:
                start = repetitive_args[1]
            end = None
            if len(repetitive_args) > 2:
                end = repetitive_args[2]
            element_id = self.table("repetitive").insert(
                    dict(
                        name=name, value=value, category=category,
                        frequency=frequency, start=start, end=end
                        ))
        else:
            element_id = self.insert(
                    dict(
                        name=name, value=value, date=date, category=category))
        return {"id": element_id}

    def _search_all_tables(self, query_impl=None, create_recurrent_elements=True):
        """
        Search both the standard table and the repetitive table for elements
        that satisfy the given condition.

        :param query_impl: condition for the search. If none (default), all elements are returned.
        :type query_impl: tinydb.queries.QueryImpl

        :param create_recurrent_elements: 'Expand' elements of the 'repetitive'
            table prior to search (used when printing) or not (used when deleting).
        :type create_recurrent_elements: bool

        :return: list[tinydb.Element]
        """

        elements = []
        if query_impl is None:
            elements.extend(self.all())
        else:
            elements.extend(self.search(query_impl))

        if create_recurrent_elements:
            for element in self.table("repetitive").all():
                for e in self._create_repetitive_elements(element):
                    if query_impl is None:
                        elements.append(e)
                    else:
                        if query_impl(e):
                            elements.append(e)
        else:
            if query_impl is None:
                elements.extend(self.table("repetitive").all())
            else:
                elements.extend(self.table("repetitive").search(query_impl))

        return elements

    def _create_repetitive_elements(self, element):
        name = element["name"]
        value = element["value"]
        category = element.get("category")
        frequency = element["frequency"].upper()
        start = element["start"]
        end = element.get("end")

        if end is None:
            end = dt.now()
            last_second = dt(int(self._name), 12, 31, 23, 59, 59)
            if end > last_second:
                end = last_second
        else:
            end = dt.strptime(end, DateItem.FORMAT)

        rrule_kwargs = dict(
                dtstart=dt.strptime(start, DateItem.FORMAT), until=end
                )
        interval = 1
        if frequency == "BIMONTHLY":
            frequency = "MONTHLY"
            interval = 2
        elif frequency == "QUARTER-YEARLY":
            frequency = "MONTHLY"
            interval = 3
        elif frequency == "HALF-YEARLY":
            frequency = "MONTHLY"
            interval = 6

        rrule_kwargs["interval"] = interval
        rule = rrule.rrule(getattr(rrule, frequency), **rrule_kwargs)

        for date in rule:
            element_name = name
            if frequency == "MONTHLY":
                element_name = "{} {}".format(name, date.strftime("%B").lower())
            yield Element(dict(
                name=element_name, value=value, category=category,
                date=date.strftime(DateItem.FORMAT)
                ))

    def find_entry(self, create_recurrent_elements=True, **query_kwargs):
        condition = self._create_query_condition(**query_kwargs)
        return self._search_all_tables(condition,
                create_recurrent_elements=create_recurrent_elements)

    def remove_entry(self, **kwargs):
        entries = self.find_entry(create_recurrent_elements=False, **kwargs)
        if entries:
            if len(entries) > 1:
                return {"error": "Ambiguous query. Nothing is removed."}
            entry = entries[0]
            self._category_cache[entry["name"]][entry["category"]] -= 1

            entry_id = entry.eid

            if entry.get("frequency", False):
                self.table("repetitive").remove(eids=[entry_id])
            else:
                self.remove(eids=[entry_id])

            return {"id": entry_id}
        return {"error": "No entry matching the query."}


    def _create_query_condition(self, name=None, value=None, category=None, date=None):
        condition = None
        entry = Query()

        for item_name in ["name", "value", "category", "date"]:
            item = locals()[item_name]
            if item is None:
                continue

            if isinstance(item, str):
                item = item.lower()

            #TODO use tinydb.Query.search
            new_condition = (entry[item_name].matches(".*{}.*".format(item)))
            if condition is None:
                condition = new_condition
            else:
                condition &= new_condition

        return condition

    def print_entries(self, **query_kwargs):
        condition = self._create_query_condition(**query_kwargs)
        return {"elements": self._search_all_tables(condition)}

def prettify(elements, stacked_layout=False):
    if not elements:
        return ""

    query = where("value") > 0
    earnings = []
    expenses = []

    for element in elements:
        if query(element):
            earnings.append(element)
        else:
            expenses.append(element)

    model_earnings = Model.from_tinydb(earnings, "Earnings")
    model_expenses = Model.from_tinydb(expenses, "Expenses")

    if stacked_layout:
        return "{}\n\n{}\n\n{}".format(
                str(model_earnings), 38*"-", str(model_expenses)
                )
    else:
        result = []
        models = [model_earnings, model_expenses]
        models_str = [str(m).splitlines() for m in models]
        for row in zip(*models_str):
            result.append(" | ".join(row))
        earnings_size = len(models_str[0])
        expenses_size = len(models_str[1])
        diff = earnings_size - expenses_size
        if diff > 0:
            for row in models_str[0][expenses_size:]:
                result.append(row + " | ")
        else:
            for row in models_str[1][earnings_size:]:
                result.append(38*" " + " | " + row)
        result.append(79*"=")
        result.append(
                " | ".join(
                    [str(CategoryEntry(name="TOTAL", sum=m.total_value()))
                        for m in models]
                    )
                )
        return '\n'.join(result)
