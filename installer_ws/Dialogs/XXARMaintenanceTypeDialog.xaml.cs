using System.Windows;
using WixSharp;
using WixSharp.UI.WPF;

namespace XXAR.Installer.Dialogs
{
    public partial class XXARMaintenanceTypeDialog : WpfDialog, IWpfDialog
    {
        private XXARDialogViewModel model;

        public XXARMaintenanceTypeDialog()
        {
            InitializeComponent();
            XXARHostStyling.RegisterDarkWpfCompositionTarget(this);
        }

        public void Init()
        {
            XXARHostStyling.ApplyDarkHost(ManagedFormHost);
            DataContext = model = new XXARDialogViewModel { Host = ManagedFormHost };
        }

        private void Repair_Click(object sender, RoutedEventArgs e)
        {
            // REINSTALLMODE=emus: reinstall all files, registry and shortcuts.
            var s = model.Session;
            if (s != null)
            {
                s["REINSTALL"] = "ALL";
                s["REINSTALLMODE"] = "emus";
                s["REMOVE"] = "";   // clear any stale Remove so the options page stays skipped on repair
            }
            model.GoNext();
        }

        private void Uninstall_Click(object sender, RoutedEventArgs e)
        {
            // The purge-mods choice is made on the next page (XXARRemoveOptionsDialog).
            var s = model.Session;
            if (s != null)
            {
                s["REMOVE"] = "ALL";
                s["REINSTALL"] = "";   // clear any stale Repair selection
            }
            model.GoNext();
        }

        private void Cancel_Click(object sender, RoutedEventArgs e) => model.Cancel();
    }
}
