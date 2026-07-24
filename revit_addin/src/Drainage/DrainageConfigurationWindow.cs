using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Interop;
using WpfBinding = System.Windows.Data.Binding;
using WpfGrid = System.Windows.Controls.Grid;

namespace RfaMetadataAddin.Drainage
{
    internal sealed class DrainageElementChoice
    {
        public long ElementIdValue { get; set; }
        public string UniqueId { get; set; }
        public string Name { get; set; }
    }

    internal sealed class DrainageConfigurationWindow : Window
    {
        private readonly Document _document;
        private readonly ObservableCollection<DrainageConfigurationProfile>
            _profiles;
        private readonly IList<DrainageElementChoice> _pipeTypes;
        private IList<DrainageElementChoice> _fittings;
        private readonly DataGrid _grid;
        private readonly System.Windows.Controls.ComboBox _pipeTypePicker;
        private readonly CheckBox _showAllFittings;

        public DrainageConfigurationWindow(UIApplication uiApplication)
        {
            if (uiApplication == null
                || uiApplication.ActiveUIDocument == null)
            {
                throw new InvalidOperationException(
                    "請先開啟 Revit 專案。");
            }

            _document = uiApplication.ActiveUIDocument.Document;
            _pipeTypes = LoadPipeTypes(_document);
            _profiles = new ObservableCollection<DrainageConfigurationProfile>(
                DrainageConfigurationStore.Load(_document).Profiles
                    ?? new List<DrainageConfigurationProfile>());
            _fittings = LoadFittings(_document, false);

            Title = "排水／Y接 管件設定";
            Width = 1120;
            Height = 560;
            MinWidth = 900;
            MinHeight = 420;
            WindowStartupLocation = WindowStartupLocation.CenterOwner;
            ResizeMode = ResizeMode.CanResize;

            var root = new WpfGrid { Margin = new Thickness(12) };
            root.RowDefinitions.Add(
                new RowDefinition { Height = GridLength.Auto });
            root.RowDefinitions.Add(
                new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            root.RowDefinitions.Add(
                new RowDefinition { Height = GridLength.Auto });
            Content = root;

            var toolbar = new StackPanel
            {
                Orientation = Orientation.Horizontal
            };
            WpfGrid.SetRow(toolbar, 0);
            root.Children.Add(toolbar);

            _pipeTypePicker = new System.Windows.Controls.ComboBox
            {
                Width = 260,
                Margin = new Thickness(0, 0, 8, 8),
                ItemsSource = _pipeTypes,
                DisplayMemberPath = "Name",
                SelectedValuePath = "ElementIdValue"
            };
            if (_pipeTypes.Count > 0)
            {
                _pipeTypePicker.SelectedIndex = 0;
            }
            toolbar.Children.Add(_pipeTypePicker);

            Button addButton = CreateButton("新增設定列");
            addButton.Click += delegate { AddProfile(); };
            toolbar.Children.Add(addButton);

            Button removeButton = CreateButton("移除選取列");
            removeButton.Click += delegate { RemoveSelectedProfile(); };
            toolbar.Children.Add(removeButton);

            _showAllFittings = new CheckBox
            {
                Content = "顯示全部管配件",
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(14, 0, 0, 8)
            };
            _showAllFittings.Checked += delegate { RefreshFittingChoices(true); };
            _showAllFittings.Unchecked += delegate { RefreshFittingChoices(false); };
            toolbar.Children.Add(_showAllFittings);

            _grid = new DataGrid
            {
                AutoGenerateColumns = false,
                CanUserAddRows = false,
                CanUserDeleteRows = false,
                SelectionMode = DataGridSelectionMode.Single,
                ItemsSource = _profiles,
                Margin = new Thickness(0, 0, 0, 10)
            };
            BuildColumns();
            WpfGrid.SetRow(_grid, 1);
            root.Children.Add(_grid);

            Button saveButton = new Button
            {
                Content = "儲存設定",
                Height = 34,
                HorizontalAlignment = HorizontalAlignment.Stretch
            };
            saveButton.Click += delegate { SaveProfiles(); };
            WpfGrid.SetRow(saveButton, 2);
            root.Children.Add(saveButton);

            IntPtr ownerHandle = uiApplication.MainWindowHandle;
            if (ownerHandle != IntPtr.Zero)
            {
                new WindowInteropHelper(this).Owner = ownerHandle;
            }
        }

        private static Button CreateButton(string text)
        {
            return new Button
            {
                Content = text,
                MinWidth = 96,
                Height = 28,
                Margin = new Thickness(0, 0, 8, 8)
            };
        }

        private void BuildColumns()
        {
            _grid.Columns.Clear();
            _grid.Columns.Add(new DataGridComboBoxColumn
            {
                Header = "管類型",
                Width = new DataGridLength(1.25, DataGridLengthUnitType.Star),
                ItemsSource = _pipeTypes,
                DisplayMemberPath = "Name",
                SelectedValuePath = "ElementIdValue",
                SelectedValueBinding = new WpfBinding("PipeTypeId")
            });
            _grid.Columns.Add(CreateFittingColumn(
                "斜 T 三通",
                "SanitaryTeeTypeId"));
            _grid.Columns.Add(CreateFittingColumn(
                "Y 三通",
                "WyeTypeId"));
            _grid.Columns.Add(CreateFittingColumn(
                "立管轉水平彎頭",
                "VerticalToHorizontalElbowTypeId"));
            _grid.Columns.Add(CreateFittingColumn(
                "45°／錯層彎頭",
                "OffsetElbowTypeId"));
            _grid.Columns.Add(CreateTextColumn(
                "支管坡度 (%)",
                "SlopePercent",
                95));
            _grid.Columns.Add(CreateTextColumn(
                "最小管徑 (mm)",
                "MinimumDiameterMm",
                105));
            _grid.Columns.Add(CreateTextColumn(
                "最大管徑 (mm)",
                "MaximumDiameterMm",
                105));
        }

        private DataGridComboBoxColumn CreateFittingColumn(
            string header,
            string bindingPath)
        {
            return new DataGridComboBoxColumn
            {
                Header = header,
                Width = new DataGridLength(1.15, DataGridLengthUnitType.Star),
                ItemsSource = _fittings,
                DisplayMemberPath = "Name",
                SelectedValuePath = "ElementIdValue",
                SelectedValueBinding = new WpfBinding(bindingPath)
            };
        }

        private static DataGridTextColumn CreateTextColumn(
            string header,
            string bindingPath,
            double width)
        {
            return new DataGridTextColumn
            {
                Header = header,
                Width = width,
                Binding = new WpfBinding(bindingPath)
                {
                    UpdateSourceTrigger =
                        UpdateSourceTrigger.LostFocus
                }
            };
        }

        private void AddProfile()
        {
            DrainageElementChoice pipeType =
                _pipeTypePicker.SelectedItem as DrainageElementChoice;
            if (pipeType == null)
            {
                MessageBox.Show(
                    this,
                    "目前專案沒有可設定的管類型。",
                    "排水管件設定",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning);
                return;
            }
            if (_profiles.Any(item =>
                item.PipeTypeId == pipeType.ElementIdValue))
            {
                MessageBox.Show(
                    this,
                    "這個管類型已經有設定列。",
                    "排水管件設定",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                return;
            }

            var profile = new DrainageConfigurationProfile
            {
                PipeTypeId = pipeType.ElementIdValue,
                PipeTypeUniqueId = pipeType.UniqueId,
                PipeTypeName = pipeType.Name
            };
            ApplyRoutingDefaults(profile);
            _profiles.Add(profile);
            _grid.SelectedItem = profile;
            _grid.ScrollIntoView(profile);
        }

        private void RemoveSelectedProfile()
        {
            DrainageConfigurationProfile selected =
                _grid.SelectedItem as DrainageConfigurationProfile;
            if (selected != null)
            {
                _profiles.Remove(selected);
            }
        }

        private void RefreshFittingChoices(bool showAll)
        {
            _fittings = LoadFittings(_document, showAll);
            BuildColumns();
        }

        private void ApplyRoutingDefaults(
            DrainageConfigurationProfile profile)
        {
            PipeType pipeType = _document.GetElement(
                new ElementId(profile.PipeTypeId)) as PipeType;
            if (pipeType == null)
            {
                return;
            }
            IList<long> junctionIds = ReadRoutingPartIds(
                pipeType,
                RoutingPreferenceRuleGroupType.Junctions);
            IList<long> elbowIds = ReadRoutingPartIds(
                pipeType,
                RoutingPreferenceRuleGroupType.Elbows);
            long junctionId = junctionIds.FirstOrDefault();
            long elbowId = elbowIds.FirstOrDefault();
            profile.WyeTypeId = junctionId;
            profile.SanitaryTeeTypeId = junctionId;
            profile.OffsetElbowTypeId = elbowId;
            profile.VerticalToHorizontalElbowTypeId = elbowId;
        }

        private void SaveProfiles()
        {
            _grid.CommitEdit(
                DataGridEditingUnit.Cell,
                true);
            _grid.CommitEdit(
                DataGridEditingUnit.Row,
                true);
            foreach (DrainageConfigurationProfile profile in _profiles)
            {
                NormalizeProfile(profile);
            }

            var configuration = new DrainageConfigurationDocument
            {
                Profiles = _profiles.ToList()
            };
            try
            {
                IList<string> errors =
                    DrainageConfigurationStore.ValidateForSave(
                        _document,
                        configuration);
                if (errors.Count > 0)
                {
                    throw new InvalidOperationException(
                        string.Join(
                            Environment.NewLine,
                            errors));
                }
                using (var transaction = new Transaction(
                    _document,
                    "儲存排水管件設定"))
                {
                    transaction.Start();
                    DrainageConfigurationStore.Save(
                        _document,
                        configuration);
                    transaction.Commit();
                }
                MessageBox.Show(
                    this,
                    "設定已儲存。",
                    "排水管件設定",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    this,
                    ex.Message,
                    "無法儲存排水管件設定",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
            }
        }

        private void NormalizeProfile(
            DrainageConfigurationProfile profile)
        {
            PipeType pipeType = _document.GetElement(
                new ElementId(profile.PipeTypeId)) as PipeType;
            if (pipeType != null)
            {
                profile.PipeTypeUniqueId = pipeType.UniqueId;
                profile.PipeTypeName = pipeType.Name;
            }
            SetFittingIdentity(
                profile.SanitaryTeeTypeId,
                delegate(string value)
                {
                    profile.SanitaryTeeTypeUniqueId = value;
                });
            SetFittingIdentity(
                profile.WyeTypeId,
                delegate(string value)
                {
                    profile.WyeTypeUniqueId = value;
                });
            SetFittingIdentity(
                profile.VerticalToHorizontalElbowTypeId,
                delegate(string value)
                {
                    profile.VerticalToHorizontalElbowTypeUniqueId = value;
                });
            SetFittingIdentity(
                profile.OffsetElbowTypeId,
                delegate(string value)
                {
                    profile.OffsetElbowTypeUniqueId = value;
                });
        }

        private void SetFittingIdentity(
            long elementId,
            Action<string> setter)
        {
            Element element = elementId > 0
                ? _document.GetElement(new ElementId(elementId))
                : null;
            setter(element == null ? "" : element.UniqueId);
        }

        private static IList<DrainageElementChoice> LoadPipeTypes(
            Document document)
        {
            return new FilteredElementCollector(document)
                .OfClass(typeof(PipeType))
                .Cast<PipeType>()
                .OrderBy(item => item.Name)
                .Select(item => new DrainageElementChoice
                {
                    ElementIdValue = item.Id.Value,
                    UniqueId = item.UniqueId,
                    Name = item.Name
                })
                .ToList();
        }

        private static IList<DrainageElementChoice> LoadFittings(
            Document document,
            bool showAll)
        {
            HashSet<long> allowedIds = null;
            if (!showAll)
            {
                allowedIds = new HashSet<long>();
                foreach (PipeType pipeType in
                    new FilteredElementCollector(document)
                        .OfClass(typeof(PipeType))
                        .Cast<PipeType>())
                {
                    foreach (long id in ReadRoutingPartIds(
                        pipeType,
                        RoutingPreferenceRuleGroupType.Junctions)
                        .Concat(ReadRoutingPartIds(
                            pipeType,
                            RoutingPreferenceRuleGroupType.Elbows)))
                    {
                        allowedIds.Add(id);
                    }
                }
            }

            return new FilteredElementCollector(document)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .Where(item => item.Category != null
                    && item.Category.Id.Value
                        == (long)BuiltInCategory.OST_PipeFitting
                    && (allowedIds == null
                        || allowedIds.Contains(item.Id.Value)))
                .OrderBy(item => item.FamilyName)
                .ThenBy(item => item.Name)
                .Select(item => new DrainageElementChoice
                {
                    ElementIdValue = item.Id.Value,
                    UniqueId = item.UniqueId,
                    Name = item.FamilyName + " : " + item.Name
                })
                .ToList();
        }

        private static IList<long> ReadRoutingPartIds(
            PipeType pipeType,
            RoutingPreferenceRuleGroupType group)
        {
            var result = new List<long>();
            RoutingPreferenceManager manager =
                pipeType.RoutingPreferenceManager;
            int count = manager.GetNumberOfRules(group);
            for (int index = 0; index < count; index++)
            {
                RoutingPreferenceRule rule = manager.GetRule(
                    group,
                    index);
                if (rule != null
                    && rule.MEPPartId != ElementId.InvalidElementId)
                {
                    result.Add(rule.MEPPartId.Value);
                }
            }
            return result;
        }
    }
}
