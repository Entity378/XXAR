using System.Windows;
using System.Windows.Controls;

namespace XXAR.Setup.Pages
{
    public partial class MaintenancePage : UserControl
    {
        private readonly MainWindow host;

        public MaintenancePage(MainWindow host)
        {
            this.host = host;
            InitializeComponent();
        }

        private void Repair_Click(object sender, RoutedEventArgs e)
        {
            // Repair reinstalls to the existing location; the engine's staging swap replaces every file.
            host.Ctx.RepairRequested = true;
            host.Go(new ProgressPage(host, uninstalling: false));
        }

        private void Uninstall_Click(object sender, RoutedEventArgs e) => host.Go(new RemoveOptionsPage(host, allowBack: true));
        private void Cancel_Click(object sender, RoutedEventArgs e) => host.CancelSetup();
    }
}
