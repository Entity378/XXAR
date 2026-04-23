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
            // REINSTALLMODE=emus: replace equal-or-lower versions, force re-cache,
            // rewrite machine-data, write user registry entries, rewrite shortcuts.
            var s = model.Session;
            if (s != null)
            {
                s["REINSTALL"] = "ALL";
                s["REINSTALLMODE"] = "emus";
            }
            model.GoNext();
        }

        private void Remove_Click(object sender, RoutedEventArgs e)
        {
            var s = model.Session;
            if (s != null)
                s["REMOVE"] = "ALL";
            model.GoNext();
        }

        private void Cancel_Click(object sender, RoutedEventArgs e) => model.Cancel();
    }
}
