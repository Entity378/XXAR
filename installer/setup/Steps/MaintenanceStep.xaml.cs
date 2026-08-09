using System.Windows;
using System.Windows.Controls;

using XXAR.Wizard;

namespace XXAR.Setup.Steps
{
    public partial class MaintenanceStep : UserControl
    {
        private readonly MainWindow wizard;

        public MaintenanceStep(MainWindow wizard)
        {
            this.wizard = wizard;
            InitializeComponent();
        }

        private void Repair_Click(object sender, RoutedEventArgs e)
        {
            // Repair reinstalls over the existing location; the staging swap replaces every file.
            wizard.Show(new ProgressStep(wizard, removing: false));
        }

        private void Remove_Click(object sender, RoutedEventArgs e)
        {
            wizard.Show(new RemoveOptionsStep(wizard, allowBack: true));
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            wizard.Abandon();
        }
    }
}
