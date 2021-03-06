#-*- coding: utf-8 -*-
from __future__ import unicode_literals

from PyQt5.QtGui import QStandardItemModel
from PyQt5.QtCore import (QVariant, Qt)
import xml.etree.ElementTree as ET
from financeager.entries import BaseEntry, CategoryEntry
from financeager.items import ValueItem, CategoryItem

try:
    QString = unicode
except NameError:
    # Python 3
    QString = str

class Model(QStandardItemModel):
    """Holds Entries in hierarchical order. First-level children are
    CategoryEntries, second-level children are BaseEntries. Generator methods
    are provided to iterate over these.
    When a `root_element` (type `ET.Element`) is passed at initialization, the
    model is built from it.
    """

    def __init__(self, root_element=None, name=None):
        super(QStandardItemModel, self).__init__()
        self._name = name
        self.itemChanged.connect(self._update_sum_item)
        self.setHorizontalHeaderLabels(
                [k.capitalize() for k in BaseEntry.ITEM_TYPES])
        if root_element is not None:
            self.create_from_xml(root_element)

    @classmethod
    def from_tinydb(cls, elements, name=None):
        model = cls(name=name)
        for element in elements:
            model.add_entry(BaseEntry(element["name"], element["value"],
                element.get("date")), category=element.get("category"))
        return model

    def __str__(self):
        result = ["{:^38}".format("Model" if self._name is None else self._name)]

        result.append("{:18} {:8} {:10}".format(*[
            self.headerData(col, Qt.Horizontal) for col in
            range(self.columnCount())])
            )

        for category_item in self.category_entry_items("name"):
            result.append(str(category_item.entry))
            for row in range(category_item.rowCount()):
                name_item = category_item.child(row)
                result.append("  " + str(name_item.entry))

        return '\n'.join(result)

    def add_entry(self, entry, category=None):
        """Add a Category- or BaseEntry to the model.
        Category names are unique, i.e. a CategoryEntry is not skipped if one
        with identical name (case INsensitive) already exists.
        When adding a BaseEntry, the parent CategoryItem is created if it does
        not exist. If no category is specified, the BaseEntry is added to the
        default category. The corresponding sum item is updated.
        """
        if category is None:
            category = CategoryItem.DEFAULT_NAME
        if isinstance(entry, CategoryEntry):
            if entry.name_item.data() not in self.category_entry_names:
                self.appendRow(entry.items)
        elif isinstance(entry, BaseEntry):
            self.add_entry(CategoryEntry(category))
            category_item = self.find_category_item(category)
            category_item.appendRow(entry.items)
            self.itemChanged.emit(entry.value_item)

    def remove_entry(self, entry, category):
        """Querying the given category, remove the first base entry whose
        attributes are a superset of the attributes of `entry`.
        The corresponding SumItem is updated.
        """
        item = self.find_name_item(name=entry.name_item.data(),
                date=entry.date_item.text(), category=category)
        category_item = item.parent()
        self.removeRow(item.row(), item.index().parent())
        if category_item.rowCount():
            self.itemChanged.emit(category_item.child(0, 1))
        else:
            #TODO remove category bc empty ?
            pass

    def category_entry_items(self, item_type):
        """Generator iterating over first-level children (CategoryEntries) of
        the model. `item_type` is one of `CategoryEntry.ITEM_TYPES`.

        raises: KeyError if `item_type` not found.
        yields: CategoryItem, SumItem
        """
        col = list(CategoryEntry.ITEM_TYPES).index(item_type)
        for row in range(self.rowCount()):
            yield self.item(row, col)

    def base_entry_items(self, item_type):
        """Generator iterating over second-level children (BaseEntries) of
        the model. `item_type` is one of `BaseEntry.ITEM_TYPES`.

        raises: KeyError if `item_type` not found.
        yields: NameItem, ValueItem, DateItem
        """
        col = list(BaseEntry.ITEM_TYPES).index(item_type)
        for category_item in self.category_entry_items("name"):
            for row in range(category_item.rowCount()):
                yield category_item.child(row, col)

    @property
    def category_entry_names(self):
        """Convenience generator method yielding category names.

        yield: QString
        """
        item_generator = self.category_entry_items("name")
        # TODO there has to be a better way
        while True:
            try:
                yield next(item_generator).data()
            except StopIteration:
                break

    def find_category_item(self, category_name):
        """Find CategoryItem by given `category_name` or return None if not
        found. The search is case insensitive.
        """
        for category_item in self.category_entry_items("name"):
            if category_item.data() == QString(category_name.lower()):
                return category_item
        return None

    def category_sum(self, category_name):
        """Return sum of category named `category_name`."""
        category_item = self.find_category_item(category_name)
        if category_item is not None:
            return category_item.entry.sum_item.value
        return 0.0

    def _update_sum_item(self, item):
        """Slot that updates the corresponding SumItem if a ValueItem is added
        or modified."""
        if isinstance(item, ValueItem):
            category_item = item.parent()
            if category_item is None:
                return
            col = list(BaseEntry.ITEM_TYPES).index("value")
            new_sum = 0.0
            for row in range(category_item.rowCount()):
                new_sum += category_item.child(row, col).value
            sum_item = category_item.entry.sum_item
            sum_item.setText(QString("{}".format(new_sum)))

    def find_name_item(self, **kwargs):
        """Find a NameItem by explicitely passing keyword arguments `name`
        and/or `value` and/or `date` and/or `category`. The first NameItem
        meeting the search requirements is returned. If no match is found,
        `None` is returned. The matching is performed case-INsensitive. If no
        category specified, the `CategoryItem.DEFAULT_NAME` category is
        queried.
        kwargs values must be of type str.
        """
        category_name = kwargs.pop("category", CategoryItem.DEFAULT_NAME)
        attributes = {v.lower() for v in kwargs.values()}
        category_item = self.find_category_item(category_name)
        if category_item is None:
            return None
        for row in range(category_item.rowCount()):
            name_item = category_item.child(row)
            other_attributes = set()
            # use .data() to get lowercase name
            other_attributes.add(name_item.data())
            other_attributes.add(name_item.entry.date_item.text())
            if attributes.issubset(other_attributes):
                return name_item
        return None

    def convert_to_xml(self):
        model_element = ET.Element("model")
        if self._name is not None:
            model_element.set("name", self._name)
        for name_item in self.base_entry_items("name"):
            entry = name_item.entry
            entry_element = ET.SubElement(
                    model_element,
                    "entry",
                    attrib=dict(
                        name=str(entry.name),
                        value=str(entry.value),
                        date=str(entry.date),
                        category=str(name_item.parent())
                        )
                    )
            entry_element.tail = "\n"
        model_element.text = "\n"
        model_element.tail = "\n"
        return model_element

    def create_from_xml(self, parent_element):
        self._name = parent_element.get("name")
        for child in parent_element:
            category_name = child.attrib.pop("category")
            self.add_entry(BaseEntry(child.attrib['name'],
                child.attrib['value'], child.attrib['date']), category_name)

    def total_value(self):
        result = 0.0
        for item in self.category_entry_items("sum"):
            result += item.data()
        return result
