package io.github.peyoteheadlights.mcsc.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import java.security.GeneralSecurityException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The sign-in token, sealed with an AES key that lives in the phone's
 * keystore (in its secure hardware where there is one) and never leaves
 * it. The sealed token can't be read on another phone or from a backup.
 */
class Vault(context: Context) {
    private val prefs = context.getSharedPreferences("vault", Context.MODE_PRIVATE)

    @Volatile
    private var cache: String? = null

    fun token(): String? {
        cache?.let { return it }
        val stored = prefs.getString(TOKEN, null) ?: return null
        val parts = stored.split(':')
        if (parts.size != 2) {
            clear()
            return null
        }
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, decode(parts[0])))
            String(cipher.doFinal(decode(parts[1])), Charsets.UTF_8).also { cache = it }
        } catch (e: GeneralSecurityException) {
            // The key is gone (the phone's lock was removed, say): sign in again.
            clear()
            null
        } catch (e: IllegalArgumentException) {
            clear()
            null
        }
    }

    fun save(token: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val sealed = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        prefs.edit { putString(TOKEN, encode(cipher.iv) + ":" + encode(sealed)) }
        cache = token
    }

    fun clear() {
        prefs.edit { remove(TOKEN) }
        cache = null
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private fun encode(bytes: ByteArray) = Base64.encodeToString(bytes, Base64.NO_WRAP)

    private fun decode(text: String) = Base64.decode(text, Base64.NO_WRAP)

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "mcsc-sign-in"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val TOKEN = "token"
    }
}
