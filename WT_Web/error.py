from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def maintenance():
    return render_template("error.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
