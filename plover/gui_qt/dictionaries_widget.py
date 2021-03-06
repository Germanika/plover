
import os
import shutil
import webbrowser
import sys

from PyQt5.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QVariant,
    Qt,
    pyqtSignal,
)
from PyQt5.QtWidgets import (
    QFileDialog,
    QTableWidgetItem,
    QWidget,
    QMenu,
    QAction,
    QMessageBox,
)

from plover import log
from plover.gui_qt.conversion_failure_dialog import ConversionFailureDialog
from plover.misc import shorten_path
from plover.registry import registry

from plover.gui_qt.dictionaries_widget_ui import Ui_DictionariesWidget
from plover.gui_qt.dictionary_editor import DictionaryEditor
from plover.gui_qt.utils import ToolBar
from plover.dictionary.base import convert_dictionary


def _dictionary_formats():
    return set(registry.list_plugins('dictionary'))


class DictionariesWidget(QWidget, Ui_DictionariesWidget):

    add_translation = pyqtSignal(QVariant)

    def __init__(self, engine):
        super(DictionariesWidget, self).__init__()
        self.setupUi(self)
        self._engine = engine
        self._states = []
        self._dictionaries = []
        self._editor = None
        for action in (
            self.action_Undo,
            self.action_EditDictionaries,
            self.action_RemoveDictionaries,
            self.action_MoveDictionariesUp,
            self.action_MoveDictionariesDown,
        ):
            action.setEnabled(False)
        # Toolbar.
        self.layout().addWidget(ToolBar(
            self.action_Undo,
            None,
            self.action_EditDictionaries,
            self.action_RemoveDictionaries,
            self.action_AddDictionaries,
            self.action_AddTranslation,
            None,
            self.action_MoveDictionariesUp,
            self.action_MoveDictionariesDown,
        ))
        self.table.supportedDropActions = self._supported_drop_actions
        self.table.dragEnterEvent = self._drag_enter_event
        self.table.dragMoveEvent = self._drag_move_event
        self.table.dropEvent = self._drop_event
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_selector)
        engine.signal_connect('config_changed', self.on_config_changed)

    def setFocus(self):
        self.table.setFocus()

    def on_config_changed(self, config_update):
        if 'dictionary_file_names' in config_update:
            if self._update_dictionaries(config_update['dictionary_file_names'],
                                         record=False, save=False,
                                         scroll=True):
                self.action_Undo.setEnabled(False)
                self._states = []

    def _update_dictionaries(self, dictionaries,
                             record=True, save=True,
                             scroll=False):
        if dictionaries == self._dictionaries:
            return False
        if save:
            self._engine.config = { 'dictionary_file_names': dictionaries }
        if record:
            self._states.append(self._dictionaries)
            self.action_Undo.setEnabled(True)
        if self._editor:
            for dictionary in self._editor.dictionary_paths:
                if dictionary not in dictionaries:
                    self._editor.close()
        self._dictionaries = dictionaries

        self.table.setRowCount(0)
        item = None
        for row, filename in enumerate(dictionaries):
            self.table.insertRow(row)
            item = QTableWidgetItem(shorten_path(filename))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, item)
        if scroll and item is not None:
            self.table.setCurrentItem(item)
        return True

    @staticmethod
    def _supported_drop_actions():
        return Qt.CopyAction | Qt.LinkAction | Qt.MoveAction

    def is_accepted_drag_event(self, event):
        if event.source() == self.table:
            return True
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                # Only support local files.
                if not url.isLocalFile():
                    break
                # And only allow supported extensions.
                filename = url.toLocalFile()
                extension = os.path.splitext(filename)[1].lower()[1:]
                if extension not in _dictionary_formats():
                    break
            else:
                return True
        return False

    def _drag_enter_event(self, event):
        if self.is_accepted_drag_event(event):
            event.accept()

    def _drag_move_event(self, event):
        if self.is_accepted_drag_event(event):
            event.accept()

    def _drop_event(self, event):
        if not self.is_accepted_drag_event(event):
            return
        dictionaries = list(self._dictionaries)
        dest_item = self.table.itemAt(event.pos())
        if dest_item is None:
            dest_index = self.table.rowCount()
        else:
            dest_index = dest_item.row()
        if event.source() == self.table:
            sources = [
                dictionaries[item.row()]
                for item in self.table.selectedItems()
            ]
        else:
            sources = [
                url.toLocalFile()
                for url in event.mimeData().urls()
            ]
        for filename in sources:
            try:
                source_index = dictionaries.index(filename)
            except ValueError:
                pass
            else:
                if source_index == dest_index:
                    dest_index += 1
                    continue
                del dictionaries[source_index]
                if source_index < dest_index:
                    dest_index -= 1
            dictionaries.insert(dest_index, filename)
            dest_index += 1
        self._update_dictionaries(dictionaries)

    def _get_selection(self):
        row_list = [item.row() for item in self.table.selectedItems()]
        row_list.sort()
        return row_list

    def _set_selection(self, row_list):
        selection = QItemSelection()
        model = self.table.model()
        for row in row_list:
            index = model.index(row, 0)
            selection.select(index, index)
        self.table.selectionModel().select(selection, QItemSelectionModel.Rows |
                                           QItemSelectionModel.ClearAndSelect |
                                           QItemSelectionModel.Current)

    def on_selection_changed(self):
        enabled = bool(self.table.selectedItems())
        for action in (
            self.action_RemoveDictionaries,
            self.action_EditDictionaries,
            self.action_MoveDictionariesUp,
            self.action_MoveDictionariesDown,
        ):
            action.setEnabled(enabled)

    def on_undo(self):
        assert self._states
        dictionaries = self._states.pop()
        self.action_Undo.setEnabled(bool(self._states))
        self._update_dictionaries(dictionaries, record=False)

    def _edit(self, dictionaries):
        if self._editor is not None:
            self._editor.close()
        self._editor = DictionaryEditor(self._engine, dictionaries)

        def on_finished():
            if self._editor:
                self._editor.destroy()
        self._editor.finished.connect(on_finished)
        self._editor.show()
        self._editor.activateWindow()
        self._editor.raise_()

    def on_activate_cell(self, row, col):
        self._edit([self._dictionaries[row]])

    def on_edit_dictionaries(self):
        dictionaries = [self._dictionaries[item.row()]
                        for item in self.table.selectedItems()]
        assert dictionaries
        self._edit(dictionaries)

    def on_remove_dictionaries(self):
        selection = self._get_selection()
        assert selection
        dictionaries = list(self._dictionaries)
        for row in sorted(selection, reverse=True):
            del dictionaries[row]
        self._update_dictionaries(dictionaries)

    def on_add_dictionaries(self):
        filters = ['*.' + ext for ext in sorted(_dictionary_formats())]
        new_filenames = QFileDialog.getOpenFileNames(
            self, _('Add dictionaries'), None,
            _('Dictionary Files') + ' (%s)' % ' '.join(filters),
        )[0]
        dictionaries = list(self._dictionaries)
        for filename in new_filenames:
            if filename not in dictionaries:
                dictionaries.append(filename)
        self._update_dictionaries(dictionaries)

    def on_add_translation(self):
        selection = self._get_selection()
        if selection:
            selection.sort()
            dictionary = self._dictionaries[selection[-1]]
        else:
            dictionary = None
        self.add_translation.emit(dictionary)

    def on_move_dictionaries_up(self):
        dictionaries = self._dictionaries[:]
        selection = []
        min_row = 0
        for old_row in self._get_selection():
            new_row = max(min_row, old_row - 1)
            dictionaries.insert(new_row, dictionaries.pop(old_row))
            selection.append(new_row)
            min_row = new_row + 1
        if dictionaries == self._dictionaries:
            return
        self._update_dictionaries(dictionaries)
        self._set_selection(selection)

    def on_move_dictionaries_down(self):
        dictionaries = self._dictionaries[:]
        selection = []
        max_row = len(dictionaries) - 1
        for old_row in reversed(self._get_selection()):
            new_row = min(max_row, old_row + 1)
            dictionaries.insert(new_row, dictionaries.pop(old_row))
            selection.append(new_row)
            max_row = new_row - 1
        if dictionaries == self._dictionaries:
            return
        self._update_dictionaries(dictionaries)
        self._set_selection(selection)

    def _row_selector(self, pos):
        menu = QMenu()

        action = QAction(_('&Save As...'), self)
        action.triggered.connect(self._save_as)
        menu.addAction(action)

        action = QAction(_('&Open Containing Folder'), self)
        action.triggered.connect(self._open_file_directory)
        menu.addAction(action)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _open_file_directory(self):
        file_name = [self._dictionaries[item.row()]
                    for item in self.table.selectedItems()][0]
        file_directory = os.path.dirname(file_name)
        if sys.platform.startswith('darwin'):
            file_directory = 'file://%s' % file_directory
        webbrowser.open(file_directory)

    def _save_as(self):
        filename = [self._dictionaries[item.row()]
                        for item in self.table.selectedItems()][0]
        file_ext = os.path.splitext(filename)[-1].lower().strip('.')


        dictionary_formats = _dictionary_formats()

        def extension_string(ext):
            fmt = _('{ext_upper} Dictionary (*{dot_ext})')
            return fmt.format(ext_upper=ext.upper(),
                              dot_ext='.' + ext)

        selected_filter = (
            extension_string(file_ext) if file_ext in dictionary_formats
            else None)

        filters = ';;'.join(extension_string(ext) for ext in dictionary_formats)

        new_filename = QFileDialog.getSaveFileName(
            self, _('Save Dictionary As...'), filename,
            filters, selected_filter
        )[0]

        if new_filename:
            file_name = os.path.basename(new_filename)
            file_directory = os.path.dirname(new_filename)
            new_ext = os.path.splitext(new_filename)[-1].lower()

            try:
                converted = None
                if file_ext == new_ext:
                    shutil.copyfile(filename, new_filename)
                else:
                    open(new_filename, 'w')
                    converted = convert_dictionary(filename, new_filename)
            except Exception:
                log.error(
                    _('Error while saving new dictionary: %s'),
                    new_filename,
                    exc_info = True
                )
            else:
                if converted:
                    if converted.save.t:
                        converted.save.t.join()
                    if converted.save.failed_entries:
                        ConversionFailureDialog(
                            converted.save.failed_entries,
                            parent=self
                        ).exec()
                fmt = ('{filename} was saved to {directory}.\n\n'
                       'Would you like to add the new dictionary to Plover?'
                )
                message = fmt.format(filename=file_name, directory=file_directory)
                if QMessageBox.question(
                        self, _('Dictionary Saved'), message,
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes
                        ) == QMessageBox.Yes:
                    dictionaries = list(self._dictionaries)
                    if new_filename not in self._dictionaries:
                        dictionaries.append(new_filename)
                    self._update_dictionaries(dictionaries)

