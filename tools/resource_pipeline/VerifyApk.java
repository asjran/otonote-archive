import com.android.apksig.ApkVerifier;
import java.io.File;
import java.security.MessageDigest;
import java.util.HexFormat;

/** Thin CLI around Google's APK verifier. Never installs or executes the APK. */
public class VerifyApk {
    public static void main(String[] args) throws Exception {
        var result = new ApkVerifier.Builder(new File(args[0])).build().verify();
        System.out.println("verified=" + result.isVerified());
        System.out.println("v2=" + result.isVerifiedUsingV2Scheme());
        System.out.println("v3=" + result.isVerifiedUsingV3Scheme());
        for (var certificate : result.getSignerCertificates()) {
            System.out.println("certificateSha256=" + HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-256").digest(certificate.getEncoded())));
        }
        if (!result.isVerified()) System.exit(1);
    }
}
