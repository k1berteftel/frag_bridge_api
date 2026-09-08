from __future__ import annotations


class FragmentBaseError(Exception):
    '''Base exception for all Fragment API library errors.'''


class ClientError(FragmentBaseError):
    """Raised for client configuration and setup issues (bad params, invalid cookies)."""


class ConfigurationError(ClientError):
    """Raised when required client parameters are missing or invalid."""
    CODE = 411

    MISSING_VARS = "Missing required parameter(s): {keys}."
    UNSUPPORTED_VERSION = "Unsupported wallet_version '{version}'. Must be one of: {supported}."
    INVALID_MNEMONIC = "Invalid mnemonic: expected 12, 18, or 24 words, got {count}."
    INVALID_API_KEY = (
        "Invalid Tonapi API key: expected at least 68 characters, got {length}. Generate a key at https://tonconsole.com."
    )
    INVALID_MONTHS = "Invalid Premium duration: choose 3, 6, or 12 months."
    INVALID_STARS_AMOUNT = "Invalid Stars amount: must be an integer between 50 and 1 000 000."
    INVALID_TON_AMOUNT = "Invalid TON amount: must be an integer between 1 and 1 000 000 000."
    INVALID_USERNAME = (
        "Invalid username '{username}'. "
        "Must be 5–32 characters and contain only letters (A–Z, a–z), digits (0–9), or underscores (_)."
    )
    INVALID_WINNERS_STARS = "Invalid winners count: must be an integer between 1 and 5."
    INVALID_WINNERS_PREMIUM = "Invalid winners count: must be an integer between 1 and 24 000."
    INVALID_STARS_PER_WINNER = "Invalid Stars per winner: must be an integer between 500 and 1 000 000."
    INVALID_PAYMENT_METHOD = "Invalid payment method '{method}'. Supported values: {supported}."


class CookieError(ClientError):
    """Raised when cookies are unreadable or missing required fields."""

    READ_FAILED = "Failed to parse cookies — expected a JSON string or a dict, got: {exc}"
    MISSING_KEYS = (
        "Fragment cookies are missing or empty for key(s): {keys}. "
        "Open fragment.com in your browser, log in, and copy fresh cookies."
    )
    UNSUPPORTED_BROWSER = "Unsupported browser: '{browser}'. Supported: {supported}."
    BROWSER_READ_FAILED = (
        "Failed to read {browser} cookies: {exc}. Make sure {browser} is installed and you are logged in to {url}."
    )
    MISSING_BROWSER_KEYS = (
        "Fragment cookies not found in {browser}: {keys}. "
        "Make sure you are logged in to {url} and have connected your TON wallet in {browser}."
    )
    EXPIRED = "Fragment session cookie expired at {expires}. Log in to fragment.com in your browser and extract fresh cookies."


class FragmentAPIError(FragmentBaseError):
    '''Raised for errors returned by Fragment API responses.'''

    CODE = 413
    NO_REQUEST_ID = (
        "Fragment did not return a request ID for '{context}'. "
        "Session may have expired — refresh your cookies."
    )


class FragmentPageError(FragmentAPIError):
    '''Raised when Fragment page cannot be fetched or API hash not found.'''

    BAD_STATUS = (
        "Fragment returned HTTP {status} for {url}. "
        "Cookies may be invalid or expired."
    )
    HASH_NOT_FOUND = (
        "Could not extract API hash from {url}. "
        "Page structure may have changed, or you are not logged in."
    )
    ITEM_NOT_FOUND = (
        "Item not found at {url}. Fragment returned HTTP 302 redirect."
    )


class UserNotFoundError(FragmentAPIError):
    """Raised when the target Telegram user is not found on Fragment."""
    CODE = 412
    NOT_FOUND = (
        "Telegram user '{username}' was not found on Fragment. Double-check the username and make sure the account exists."
    )


class AnonymousNumberError(FragmentAPIError):
    """Raised for Fragment anonymous number API failures."""

    NOT_OWNED = "Number '{number}' is not associated with your Fragment account or has no active sessions to terminate."
    TERMINATE_FAILED = "Failed to terminate sessions for '{number}': {error}"


class TransactionError(FragmentAPIError):
    """Raised when a TON transaction fails to build or broadcast."""

    INVALID_PAYLOAD = (
        "Fragment returned an invalid transaction payload — 'transaction.messages' is missing or empty in the API response."
    )
    BROADCAST_FAILED = "Transaction broadcast failed: {exc}"
    BROADCAST_FAILED_SSL = (
        "Transaction broadcast failed due to an SSL certificate error: {exc}\n"
        "This usually means your system's CA bundle is missing or outdated.\n"
        "Fix: run `pip install --upgrade certifi` and retry. "
        "On macOS you may also need to run the 'Install Certificates.command' "
        "located in your Python installation folder."
    )
    DUPLICATE_SEQNO = (
        "Transaction broadcast failed: the TON wallet rejected the message "
        "because a previous transaction with the same sequence number (seqno) "
        "is still pending confirmation on-chain.\n"
        "Wait a few seconds for the previous transaction to confirm, then retry."
    )


class ConfirmationTimeout(TransactionError):
    '''Raised when seqno/balance confirmation times out.

    The TON was likely sent but confirmation was not received
    within the timeout window. Manual check is recommended.
    '''

    TIMEOUT = (
        "Transaction confirmation timed out after {seconds}s. "
        "TON may have been sent — check the blockchain manually. "
        "seqno_before={seqno_before}, balance_before={balance_before:.4f} TON."
    )


class SeqnoError(TransactionError):
    '''Raised when seqno retrieval or validation fails.'''

    FETCH_FAILED = "Failed to fetch wallet seqno: {exc}"
    STALE = (
        "Seqno did not increment after {seconds}s. "
        "Transaction may not have been accepted by the network."
    )


class ParseError(FragmentAPIError):
    """Raised when a Fragment API response or payload cannot be parsed."""

    UNPARSEABLE = "Failed to parse the Fragment API response for '{context}': {exc}"


class VerificationError(FragmentAPIError):
    """Raised when Fragment requires KYC verification before proceeding."""

    KYC_REQUIRED = (
        "Fragment requires identity verification (KYC) before this action can be completed. "
        "Complete verification at https://fragment.com/my/profile and retry."
    )


class OperationError(FragmentBaseError):
    """Raised for runtime operation failures unrelated to Fragment's API."""


class ProxyError(OperationError):
    '''Raised when TON API proxy is unavailable.'''

    PROXY_UNAVAILABLE = (
        "TON API proxy at {url} is unavailable: {exc}. "
        "Please provide an api_key parameter to use the "
        "standard tonapi.io endpoint."
    )


class WalletError(OperationError):
    '''Raised for TON wallet issues.'''

    LOW_BALANCE = (
        "Insufficient balance: {balance:.4f} {currency} available, "
        "{required:.4f} {currency} required "
        "(amount + {gas:.3f} {currency} gas)."
    )
    BALANCE_FAILED = "Failed to fetch wallet balance: {exc}"
    ACCOUNT_INFO_FAILED = "Failed to retrieve wallet account info: {exc}"
    WALLET_INFO_FAILED = "Failed to retrieve wallet info: {exc}"


class UnexpectedError(OperationError):
    """Raised when an unexpected error occurs during an API call."""

    CODE = 423
    UNEXPECTED = "An unexpected error occurred during the operation: {exc}"
