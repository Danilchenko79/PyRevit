# -*- coding: utf-8 -*-
"""WPF windows for the level-based sheet tool. All UI text is English."""

from pyrevit import forms

from System.Windows.Controls import (
    TextBox, TextBlock, RadioButton, ComboBox, CheckBox, StackPanel, Orientation,
)
from System.Windows import Thickness, HorizontalAlignment, VerticalAlignment

from PEER_Sheets.levels import get_pr_level_raw
from PEER_Sheets.naming import ft_to_m, format_num, parse_elev


# ---------------------------------------------------------------------------
# Main window: review/edit PR_Level + choose elevation source + title block
# ---------------------------------------------------------------------------

MAIN_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PEER - Create Sheets by Level"
        Width="640" Height="660" MinWidth="520" MinHeight="460"
        ResizeMode="CanResizeWithGrip"
        WindowStartupLocation="CenterScreen"
        FontFamily="Segoe UI" FontSize="13">
    <Grid Margin="16,14,16,14">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*" MinHeight="120"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0"
                   Text="Review the PR_Level value of each level. Only levels with a value get sheets."
                   TextWrapping="Wrap" Margin="0,0,0,8"/>

        <!-- Header row -->
        <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="6,0,0,4">
            <TextBlock Text="Level" Width="280" FontWeight="Bold"/>
            <TextBlock Text="Elevation (m)" Width="120" FontWeight="Bold"/>
            <TextBlock Text="PR_Level" Width="90" FontWeight="Bold"/>
        </StackPanel>

        <!-- Levels table -->
        <Border Grid.Row="2" BorderBrush="#BBBBBB" BorderThickness="1" Background="White">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="levels_panel" Margin="6,4,6,4"/>
            </ScrollViewer>
        </Border>

        <Separator Grid.Row="3" Margin="0,12,0,10"/>

        <!-- Elevation source -->
        <StackPanel Grid.Row="4" Margin="0,0,0,12">
            <TextBlock Text="Elevation used in sheet names:" FontWeight="Bold" Margin="0,0,0,6"/>
            <RadioButton x:Name="src_slab"
                         Content="By top of slab (overcant)  -  pick a slab per level if several exist"
                         GroupName="src" IsChecked="True" Margin="6,0,0,5"
                         Checked="src_changed"/>
            <RadioButton x:Name="src_level"
                         Content="By level elevation"
                         GroupName="src" Margin="6,0,0,5"
                         Checked="src_changed"/>
            <CheckBox x:Name="repick_slabs"
                      Content="Re-choose slabs (ignore saved choices for levels with several slabs)"
                      Margin="24,2,0,0"/>
        </StackPanel>

        <!-- Title block -->
        <StackPanel Grid.Row="5" Orientation="Horizontal" Margin="0,0,0,16">
            <TextBlock Text="Title block:" FontWeight="Bold"
                       VerticalAlignment="Center" Margin="0,0,10,0"/>
            <ComboBox x:Name="tb_combo" Width="380"/>
        </StackPanel>

        <!-- Buttons -->
        <StackPanel Grid.Row="6" Orientation="Horizontal" HorizontalAlignment="Right">
            <Button x:Name="btn_cancel" Content="Cancel" Width="90" Height="30"
                    Margin="0,0,10,0" Click="btn_cancel_click"/>
            <Button x:Name="btn_ok" Content="Continue" Width="110" Height="30"
                    Click="btn_ok_click"/>
        </StackPanel>
    </Grid>
</Window>
"""


class _LevelRow(object):
    def __init__(self, level, textbox, original_raw):
        self.level = level
        self.textbox = textbox
        self.original_raw = original_raw


class MainWindow(forms.WPFWindow):
    def __init__(self, levels, titleblocks, saved_tb_uid=None):
        forms.WPFWindow.__init__(self, xaml_source=MAIN_XAML, literal_string=True)
        self.result = None
        self._rows = []
        self._titleblocks = list(titleblocks)

        for lvl in levels:
            row_panel = StackPanel()
            row_panel.Orientation = Orientation.Horizontal
            row_panel.Margin = Thickness(2, 3, 2, 3)

            name_tb = TextBlock()
            name_tb.Text = lvl.Name
            name_tb.Width = 280
            name_tb.VerticalAlignment = VerticalAlignment.Center

            elev_tb = TextBlock()
            elev_tb.Text = u"{0:.2f}".format(ft_to_m(lvl.Elevation))
            elev_tb.Width = 120
            elev_tb.VerticalAlignment = VerticalAlignment.Center

            raw = get_pr_level_raw(lvl)
            edit = TextBox()
            edit.Text = raw
            edit.Width = 80
            edit.HorizontalAlignment = HorizontalAlignment.Left

            row_panel.Children.Add(name_tb)
            row_panel.Children.Add(elev_tb)
            row_panel.Children.Add(edit)
            self.levels_panel.Children.Add(row_panel)

            self._rows.append(_LevelRow(lvl, edit, raw))

        for tb in self._titleblocks:
            self.tb_combo.Items.Add(tb.FamilyName)
        if self._titleblocks:
            preselect = 0
            if saved_tb_uid:
                for i, tb in enumerate(self._titleblocks):
                    if tb.UniqueId == saved_tb_uid:
                        preselect = i
                        break
            self.tb_combo.SelectedIndex = preselect

        self._update_repick_visibility()

    def src_changed(self, sender, args):
        self._update_repick_visibility()

    def _update_repick_visibility(self):
        chk = getattr(self, "repick_slabs", None)
        slab = getattr(self, "src_slab", None)
        if chk is None or slab is None:
            return
        from System.Windows import Visibility
        chk.Visibility = (Visibility.Visible if slab.IsChecked
                          else Visibility.Collapsed)

    def btn_ok_click(self, sender, args):
        if self.tb_combo.SelectedIndex < 0:
            forms.alert("Please select a title block.")
            return

        bad = []
        for r in self._rows:
            raw = (r.textbox.Text or u"").strip().replace(u",", u".")
            if not raw:
                continue
            try:
                v = float(raw)
            except ValueError:
                bad.append(r.level.Name)
                continue
            if v <= 0 or v != int(v) or int(v) % 10 != 0:
                bad.append(r.level.Name)
        if bad:
            forms.alert(u"PR_Level must be a positive multiple of 10 "
                        u"(100, 110, 120, ...).\n\nFix these levels:\n - "
                        + u"\n - ".join(bad))
            return

        pr_values = {}
        for r in self._rows:
            pr_values[r.level.Id.IntegerValue] = (
                r.level, r.textbox.Text.strip(), r.original_raw
            )

        self.result = {
            "pr_values": pr_values,
            "elev_source": "slab" if self.src_slab.IsChecked else "level",
            "repick_slabs": bool(self.repick_slabs.IsChecked),
            "titleblock": self._titleblocks[self.tb_combo.SelectedIndex],
        }
        self.Close()

    def btn_cancel_click(self, sender, args):
        self.result = None
        self.Close()


# ---------------------------------------------------------------------------
# Slab chooser: pick one slab per level when several exist (overcant mode)
# ---------------------------------------------------------------------------

SLAB_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PEER - Choose Slab per Level"
        Width="560" Height="520" MinWidth="460" MinHeight="320"
        ResizeMode="CanResizeWithGrip"
        WindowStartupLocation="CenterScreen"
        FontFamily="Segoe UI" FontSize="13">
    <Grid Margin="16,14,16,14">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*" MinHeight="120"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0"
                   Text="These levels have more than one slab. Pick the slab whose top elevation should be used."
                   TextWrapping="Wrap" Margin="0,0,0,10"/>

        <Border Grid.Row="1" BorderBrush="#BBBBBB" BorderThickness="1" Background="White">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="rows_panel" Margin="6,6,6,6"/>
            </ScrollViewer>
        </Border>

        <StackPanel Grid.Row="2" Orientation="Horizontal"
                    HorizontalAlignment="Right" Margin="0,12,0,0">
            <Button x:Name="btn_cancel" Content="Cancel" Width="90" Height="30"
                    Margin="0,0,10,0" Click="btn_cancel_click"/>
            <Button x:Name="btn_ok" Content="Create Sheets" Width="130" Height="30"
                    Click="btn_ok_click"/>
        </StackPanel>
    </Grid>
</Window>
"""


class _SlabRow(object):
    def __init__(self, level, combo, options):
        self.level = level
        self.combo = combo
        self.options = options  # list of (floor, top_elev_m)


class SlabChooserWindow(forms.WPFWindow):
    def __init__(self, ambiguous):
        """ambiguous: list of (level, base, [(floor, top_elev_m), ...], preselect).

        `preselect` is the index of the previously chosen slab (0 if none).
        """
        forms.WPFWindow.__init__(self, xaml_source=SLAB_XAML, literal_string=True)
        self.result = None
        self._rows = []

        for level, base, options, preselect in ambiguous:
            block = StackPanel()
            block.Margin = Thickness(2, 4, 2, 10)

            head = TextBlock()
            head.Text = u"{}  (PR_Level {})".format(level.Name, base)
            head.FontWeight = self._bold()
            head.Margin = Thickness(0, 0, 0, 4)

            combo = ComboBox()
            combo.Width = 460
            combo.HorizontalAlignment = HorizontalAlignment.Left
            for floor, top_m in options:
                combo.Items.Add(
                    u"Floor {}  ->  top {:.2f} m".format(floor.Id.IntegerValue, top_m))
            combo.SelectedIndex = preselect if 0 <= preselect < len(options) else 0

            block.Children.Add(head)
            block.Children.Add(combo)
            self.rows_panel.Children.Add(block)

            self._rows.append(_SlabRow(level, combo, options))

    def _bold(self):
        from System.Windows import FontWeights
        return FontWeights.Bold

    def btn_ok_click(self, sender, args):
        chosen = {}
        for r in self._rows:
            idx = r.combo.SelectedIndex
            if idx < 0:
                idx = 0
            floor, top_m = r.options[idx]
            chosen[r.level.Id.IntegerValue] = (floor, top_m)
        self.result = chosen
        self.Close()

    def btn_cancel_click(self, sender, args):
        self.result = None
        self.Close()


# ---------------------------------------------------------------------------
# Review window: confirm per sheet before creating / renaming (was -> now)
# ---------------------------------------------------------------------------

REVIEW_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PEER - Confirm Sheet Changes"
        Width="820" Height="600" MinWidth="640" MinHeight="360"
        ResizeMode="CanResizeWithGrip"
        WindowStartupLocation="CenterScreen"
        FontFamily="Segoe UI" FontSize="13">
    <Grid Margin="16,14,16,14">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*" MinHeight="120"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0"
                   Text="Check the sheets to apply. New sheets are created; existing sheets are renamed. Unchecked rows are left untouched."
                   TextWrapping="Wrap" Margin="0,0,0,8"/>

        <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="6,0,0,4">
            <TextBlock Text="Apply" Width="50" FontWeight="Bold"/>
            <TextBlock Text="No." Width="60" FontWeight="Bold"/>
            <TextBlock Text="Status" Width="80" FontWeight="Bold"/>
            <TextBlock Text="Current name" Width="300" FontWeight="Bold"/>
            <TextBlock Text="New name" Width="300" FontWeight="Bold"/>
        </StackPanel>

        <Border Grid.Row="2" BorderBrush="#BBBBBB" BorderThickness="1" Background="White">
            <ScrollViewer VerticalScrollBarVisibility="Auto"
                          HorizontalScrollBarVisibility="Auto">
                <StackPanel x:Name="rows_panel" Margin="6,4,6,4"/>
            </ScrollViewer>
        </Border>

        <StackPanel Grid.Row="3" Orientation="Horizontal"
                    HorizontalAlignment="Right" Margin="0,12,0,0">
            <Button x:Name="btn_all" Content="Select all" Width="90" Height="30"
                    Margin="0,0,10,0" Click="btn_all_click"/>
            <Button x:Name="btn_none" Content="Clear all" Width="90" Height="30"
                    Margin="0,0,20,0" Click="btn_none_click"/>
            <Button x:Name="btn_cancel" Content="Cancel" Width="90" Height="30"
                    Margin="0,0,10,0" Click="btn_cancel_click"/>
            <Button x:Name="btn_ok" Content="Apply" Width="110" Height="30"
                    Click="btn_ok_click"/>
        </StackPanel>
    </Grid>
</Window>
"""


class ReviewWindow(forms.WPFWindow):
    """Confirm which planned sheets to create/rename.

    `items` are dicts from creation.build_diff(); only items with status
    'new' or 'rename' are shown. On Apply, sets item['apply'] = checkbox state
    and self.result = True.
    """

    def __init__(self, items):
        forms.WPFWindow.__init__(self, xaml_source=REVIEW_XAML, literal_string=True)
        self.result = None
        self.items = items
        self._checks = []

        for it in items:
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Margin = Thickness(2, 3, 2, 3)

            chk = CheckBox()
            chk.IsChecked = True
            chk.Width = 50
            chk.VerticalAlignment = VerticalAlignment.Center

            num_tb = TextBlock()
            num_tb.Text = it["number"]
            num_tb.Width = 60
            num_tb.VerticalAlignment = VerticalAlignment.Center

            status_tb = TextBlock()
            status_tb.Text = it["status"]
            status_tb.Width = 80
            status_tb.VerticalAlignment = VerticalAlignment.Center

            cur_tb = TextBlock()
            cur_tb.Text = it["current_name"] if it["current_name"] else u"(new sheet)"
            cur_tb.Width = 300
            cur_tb.TextWrapping = self._wrap()
            cur_tb.VerticalAlignment = VerticalAlignment.Center

            new_tb = TextBlock()
            new_tb.Text = it["new_name"]
            new_tb.Width = 300
            new_tb.TextWrapping = self._wrap()
            new_tb.VerticalAlignment = VerticalAlignment.Center

            row.Children.Add(chk)
            row.Children.Add(num_tb)
            row.Children.Add(status_tb)
            row.Children.Add(cur_tb)
            row.Children.Add(new_tb)
            self.rows_panel.Children.Add(row)

            self._checks.append((it, chk))

    def _wrap(self):
        from System.Windows import TextWrapping
        return TextWrapping.Wrap

    def _set_all(self, value):
        for _it, chk in self._checks:
            chk.IsChecked = value

    def btn_all_click(self, sender, args):
        self._set_all(True)

    def btn_none_click(self, sender, args):
        self._set_all(False)

    def btn_ok_click(self, sender, args):
        for it, chk in self._checks:
            it["apply"] = bool(chk.IsChecked)
        self.result = True
        self.Close()

    def btn_cancel_click(self, sender, args):
        self.result = None
        self.Close()


# ---------------------------------------------------------------------------
# Label editor (Shift mode): custom elevation text per level, for names only
# ---------------------------------------------------------------------------

LABEL_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PEER - Edit Elevation Labels"
        Width="660" Height="560" MinWidth="520" MinHeight="320"
        ResizeMode="CanResizeWithGrip"
        WindowStartupLocation="CenterScreen"
        FontFamily="Segoe UI" FontSize="13">
    <Grid Margin="16,14,16,14">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*" MinHeight="120"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0"
                   Text="Type a plain elevation number (e.g. -14, 5, 5.1) used in sheet names only. Sign and decimal are formatted automatically for the Hebrew name. Leave blank to use the computed elevation."
                   TextWrapping="Wrap" Margin="0,0,0,8"/>

        <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="6,0,0,4">
            <TextBlock Text="Level" Width="220" FontWeight="Bold"/>
            <TextBlock Text="PR_Level" Width="80" FontWeight="Bold"/>
            <TextBlock Text="Computed (m)" Width="120" FontWeight="Bold"/>
            <TextBlock Text="Custom (m)" Width="160" FontWeight="Bold"/>
        </StackPanel>

        <Border Grid.Row="2" BorderBrush="#BBBBBB" BorderThickness="1" Background="White">
            <ScrollViewer VerticalScrollBarVisibility="Auto">
                <StackPanel x:Name="rows_panel" Margin="6,4,6,4"/>
            </ScrollViewer>
        </Border>

        <StackPanel Grid.Row="3" Orientation="Horizontal"
                    HorizontalAlignment="Right" Margin="0,12,0,0">
            <Button x:Name="btn_cancel" Content="Cancel" Width="90" Height="30"
                    Margin="0,0,10,0" Click="btn_cancel_click"/>
            <Button x:Name="btn_ok" Content="Save" Width="110" Height="30"
                    Click="btn_ok_click"/>
        </StackPanel>
    </Grid>
</Window>
"""


class _LabelRow(object):
    def __init__(self, unique_id, textbox):
        self.unique_id = unique_id
        self.textbox = textbox


class LabelEditorWindow(forms.WPFWindow):
    """Edit per-level elevation labels (Shift mode).

    `rows` is a list of (level, base, computed_str, saved_label_or_None).
    On Save, self.result is a dict {level.UniqueId: raw_text} for every row
    (empty text means 'no override').
    """

    def __init__(self, rows):
        forms.WPFWindow.__init__(self, xaml_source=LABEL_XAML, literal_string=True)
        self.result = None
        self._rows = []

        for level, base, computed_str, saved_label in rows:
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Margin = Thickness(2, 3, 2, 3)

            name_tb = TextBlock()
            name_tb.Text = level.Name
            name_tb.Width = 220
            name_tb.VerticalAlignment = VerticalAlignment.Center

            base_tb = TextBlock()
            base_tb.Text = str(base)
            base_tb.Width = 80
            base_tb.VerticalAlignment = VerticalAlignment.Center

            comp_tb = TextBlock()
            comp_tb.Text = computed_str
            comp_tb.Width = 120
            comp_tb.VerticalAlignment = VerticalAlignment.Center

            edit = TextBox()
            edit.Text = saved_label if saved_label else u""
            edit.Width = 150
            edit.HorizontalAlignment = HorizontalAlignment.Left

            row.Children.Add(name_tb)
            row.Children.Add(base_tb)
            row.Children.Add(comp_tb)
            row.Children.Add(edit)
            self.rows_panel.Children.Add(row)

            self._rows.append(_LabelRow(level.UniqueId, edit))

    def btn_ok_click(self, sender, args):
        result = {}
        for r in self._rows:
            raw = (r.textbox.Text or u"").strip()
            if not raw:
                result[r.unique_id] = u""
                continue
            num = parse_elev(raw)
            if num is None:
                forms.alert(
                    u"'{}' is not a valid number. "
                    u"Use values like -14, 5, 5.1.".format(raw))
                return
            result[r.unique_id] = format_num(num)  # store canonical natural form
        self.result = result
        self.Close()

    def btn_cancel_click(self, sender, args):
        self.result = None
        self.Close()


# ---------------------------------------------------------------------------
# Orphan window: confirm deletion of tool sheets whose level is gone
# ---------------------------------------------------------------------------

ORPHAN_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="PEER - Orphaned Sheets"
        Width="720" Height="520" MinWidth="560" MinHeight="320"
        ResizeMode="CanResizeWithGrip"
        WindowStartupLocation="CenterScreen"
        FontFamily="Segoe UI" FontSize="13">
    <Grid Margin="16,14,16,14">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*" MinHeight="120"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0"
                   Text="These sheets were created by this tool but their level no longer has a matching PR_Level (level deleted or PR_Level changed/cleared). Check the ones to DELETE. Unchecked sheets are kept and forgotten."
                   TextWrapping="Wrap" Margin="0,0,0,8"/>

        <StackPanel Grid.Row="1" Orientation="Horizontal" Margin="6,0,0,4">
            <TextBlock Text="Delete" Width="60" FontWeight="Bold"/>
            <TextBlock Text="No." Width="70" FontWeight="Bold"/>
            <TextBlock Text="Sheet name" Width="460" FontWeight="Bold"/>
        </StackPanel>

        <Border Grid.Row="2" BorderBrush="#BBBBBB" BorderThickness="1" Background="White">
            <ScrollViewer VerticalScrollBarVisibility="Auto"
                          HorizontalScrollBarVisibility="Auto">
                <StackPanel x:Name="rows_panel" Margin="6,4,6,4"/>
            </ScrollViewer>
        </Border>

        <StackPanel Grid.Row="3" Orientation="Horizontal"
                    HorizontalAlignment="Right" Margin="0,12,0,0">
            <Button x:Name="btn_all" Content="Select all" Width="90" Height="30"
                    Margin="0,0,10,0" Click="btn_all_click"/>
            <Button x:Name="btn_none" Content="Clear all" Width="90" Height="30"
                    Margin="0,0,20,0" Click="btn_none_click"/>
            <Button x:Name="btn_cancel" Content="Cancel" Width="90" Height="30"
                    Margin="0,0,10,0" Click="btn_cancel_click"/>
            <Button x:Name="btn_ok" Content="Continue" Width="110" Height="30"
                    Click="btn_ok_click"/>
        </StackPanel>
    </Grid>
</Window>
"""


class OrphanWindow(forms.WPFWindow):
    """Confirm which orphaned tool sheets to delete.

    `orphans` are dicts from creation.build_diff(). On Continue, sets
    orphan['apply'] = checkbox state (delete) and self.result = True.
    Delete is unchecked by default (deletion is destructive).
    """

    def __init__(self, orphans):
        forms.WPFWindow.__init__(self, xaml_source=ORPHAN_XAML, literal_string=True)
        self.result = None
        self._checks = []

        for orf in orphans:
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            row.Margin = Thickness(2, 3, 2, 3)

            chk = CheckBox()
            chk.IsChecked = False
            chk.Width = 60
            chk.VerticalAlignment = VerticalAlignment.Center

            num_tb = TextBlock()
            num_tb.Text = orf["number"]
            num_tb.Width = 70
            num_tb.VerticalAlignment = VerticalAlignment.Center

            name_tb = TextBlock()
            name_tb.Text = orf["name"]
            name_tb.Width = 460
            name_tb.VerticalAlignment = VerticalAlignment.Center

            row.Children.Add(chk)
            row.Children.Add(num_tb)
            row.Children.Add(name_tb)
            self.rows_panel.Children.Add(row)

            self._checks.append((orf, chk))

    def _set_all(self, value):
        for _orf, chk in self._checks:
            chk.IsChecked = value

    def btn_all_click(self, sender, args):
        self._set_all(True)

    def btn_none_click(self, sender, args):
        self._set_all(False)

    def btn_ok_click(self, sender, args):
        for orf, chk in self._checks:
            orf["apply"] = bool(chk.IsChecked)
        self.result = True
        self.Close()

    def btn_cancel_click(self, sender, args):
        self.result = None
        self.Close()
