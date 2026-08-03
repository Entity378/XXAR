using System.Linq;
using System.Windows;
using System.Windows.Controls;
using XXAR.Wizard;

namespace XXAR.Uninstall.Steps
{
    public partial class ChoicesStep : UserControl
    {
        private readonly MainWindow wizard;

        public ChoicesStep(MainWindow wizard)
        {
            this.wizard = wizard;
            InitializeComponent();

            var plan = wizard.Plan;
            Frame.Subheading = plan.InstalledVersion != null
                ? $"Version {plan.InstalledVersion} — installed in {plan.InstalledRoot}"
                : plan.InstalledRoot;

            // A group that is not on disk would only be confusing: there is nothing to choose about it.
            GroupList.ItemsSource = plan.Groups.Where(group => group.Bytes > 0 || group.Required).ToList();
            ShowTotal();
        }

        // Written here rather than through the binding: the order of the write-back and this event is
        // not defined, and the total has to be computed after the change.
        private void Selection_Changed(object sender, RoutedEventArgs e)
        {
            if (sender is CheckBox box && box.DataContext is RemovalGroup group)
                group.Selected = box.IsChecked == true;
            ShowTotal();
        }

        private void ShowTotal()
        {
            // TotalLabel is still null while the template is being applied during construction.
            if (TotalLabel == null) return;
            TotalLabel.Text = $"About {Sizes.Describe(wizard.Plan.SelectedBytes)} will be freed.";
        }

        private void Remove_Click(object sender, RoutedEventArgs e)
        {
            wizard.Show(new ProgressStep(wizard));
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            wizard.Close(1);
        }
    }
}
