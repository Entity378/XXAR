using System.Windows;
using WixSharp;
using WixSharp.UI.WPF;

namespace XXAR.Installer.Dialogs
{
    // Intermediate page shown only for a Remove: lets the user also wipe mods/settings before uninstalling.
    // A Repair skips it and goes straight to progress.
    public partial class XXARRemoveOptionsDialog : WpfDialog, IWpfDialog
    {
        private XXARDialogViewModel model;

        public XXARRemoveOptionsDialog()
        {
            InitializeComponent();
            XXARHostStyling.RegisterDarkWpfCompositionTarget(this);
        }

        public void Init()
        {
            if (XXARSilentUpdate.IsActive(ManagedFormHost)) { XXARSilentUpdate.SkipTo(this, ManagedFormHost.Shell.GoNext); return; }
            // Only relevant when removing; a Repair (REMOVE not set) skips this page.
            if (ManagedFormHost?.Runtime?.Session?.Property("REMOVE") != "ALL") { XXARSilentUpdate.SkipTo(this, ManagedFormHost.Shell.GoNext); return; }
            XXARHostStyling.ApplyDarkHost(ManagedFormHost);
            DataContext = model = new XXARDialogViewModel { Host = ManagedFormHost };
        }

        private void GoPrev_Click(object sender, RoutedEventArgs e) => model.GoPrev();
        private void Cancel_Click(object sender, RoutedEventArgs e) => model.Cancel();

        private void Uninstall_Click(object sender, RoutedEventArgs e)
        {
            var s = model.Session;
            if (s != null)
                s["XXAR_PURGE_USERDATA"] = (PurgeUserData.IsChecked == true) ? "1" : "0";
            model.GoNext();
        }
    }
}
