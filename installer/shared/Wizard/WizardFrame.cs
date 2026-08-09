using System.Windows;
using System.Windows.Controls;

namespace XXAR.Wizard
{
    // The chrome every step shares: branding, heading block and button bar. Each step supplies only
    // its body and its buttons, so the layout lives in exactly one place.
    // Its own namespace because the uninstaller links this file too.
    public class WizardFrame : ContentControl
    {
        public static readonly DependencyProperty HeadingProperty =
            DependencyProperty.Register(nameof(Heading), typeof(string), typeof(WizardFrame));

        public static readonly DependencyProperty SubheadingProperty =
            DependencyProperty.Register(nameof(Subheading), typeof(string), typeof(WizardFrame));

        public static readonly DependencyProperty ButtonsProperty =
            DependencyProperty.Register(nameof(Buttons), typeof(object), typeof(WizardFrame));

        // Sidebar puts the logo down the left and the heading in large type, the way the first and
        // last steps of an installer look. Otherwise the logo sits in a compact top banner.
        public static readonly DependencyProperty UseSidebarProperty =
            DependencyProperty.Register(nameof(UseSidebar), typeof(bool), typeof(WizardFrame));

        public string Heading
        {
            get { return (string)GetValue(HeadingProperty); }
            set { SetValue(HeadingProperty, value); }
        }

        public string Subheading
        {
            get { return (string)GetValue(SubheadingProperty); }
            set { SetValue(SubheadingProperty, value); }
        }

        public object Buttons
        {
            get { return GetValue(ButtonsProperty); }
            set { SetValue(ButtonsProperty, value); }
        }

        public bool UseSidebar
        {
            get { return (bool)GetValue(UseSidebarProperty); }
            set { SetValue(UseSidebarProperty, value); }
        }
    }
}
