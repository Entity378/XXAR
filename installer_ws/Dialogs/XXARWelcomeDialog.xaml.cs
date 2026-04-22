using System.Windows;
using WixSharp;
using WixSharp.UI.WPF;

namespace XXAR.Installer.Dialogs
{
    public partial class XXARWelcomeDialog : WpfDialog, IWpfDialog
    {
        private XXARDialogViewModel model;

        public XXARWelcomeDialog()
        {
            InitializeComponent();
            XXARHostStyling.RegisterDarkWpfCompositionTarget(this);
        }

        public void Init()
        {
            XXARHostStyling.ApplyDarkHost(ManagedFormHost);
            DataContext = model = new XXARDialogViewModel { Host = ManagedFormHost };
        }

        private void GoPrev_Click(object sender, RoutedEventArgs e) => model.GoPrev();
        private void GoNext_Click(object sender, RoutedEventArgs e) => model.GoNext();
        private void Cancel_Click(object sender, RoutedEventArgs e) => model.Cancel();
    }
}
