import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, flash
print("RETAILPRO APP FILE:", __file__)

app = Flask(__name__)
app.secret_key = "retailpro-dev-key"

import os
print("TEMPLATES FOLDER:", os.path.abspath(app.template_folder))
print("TEMPLATE FILE EXISTS:", os.path.exists(
    os.path.join(app.template_folder, "transactions.html")
))

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="Your password",
        database="oursol_retail_biller"
    )



@app.route("/")
def home():
    connection = None
    cursor = None

    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    # Validate the date range.
    from datetime import datetime

    try:
        if start_date:
            datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            datetime.strptime(end_date, "%Y-%m-%d")

        if start_date and end_date and start_date > end_date:
            flash("Start date cannot be after end date.", "error")
            start_date = ""
            end_date = ""

    except ValueError:
        flash("Please select valid dates.", "error")
        start_date = ""
        end_date = ""

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Count active products (not affected by the date filter).
        cursor.execute(
            "SELECT COUNT(*) AS product_count "
            "FROM products WHERE is_active = TRUE"
        )
        product_count = cursor.fetchone()["product_count"]

        # Build the date filter for completed bills.
        date_conditions = ["bill_status = 'Completed'"]
        date_params = []

        if start_date:
            date_conditions.append("bill_date >= %s")
            date_params.append(start_date + " 00:00:00")

        if end_date:
            date_conditions.append(
                "bill_date < DATE_ADD(%s, INTERVAL 1 DAY)"
            )
            date_params.append(end_date)

        date_where = " AND ".join(date_conditions)

        # Sales metrics for the selected date range.
        cursor.execute(
            f"""
            SELECT
                COALESCE(SUM(final_amount), 0) AS total_sales,
                COUNT(*) AS completed_bills,
                COALESCE(AVG(final_amount), 0) AS average_bill_value
            FROM bills
            WHERE {date_where}
            """,
            tuple(date_params)
        )
        sales_data = cursor.fetchone()

        # Best-selling product for the selected date range.
        cursor.execute(
            f"""
            SELECT
                bi.product_name,
                SUM(bi.quantity) AS total_quantity
            FROM bill_items AS bi
            JOIN bills AS b ON b.bill_id = bi.bill_id
            WHERE {date_where.replace('bill_status', 'b.bill_status').replace('bill_date', 'b.bill_date')}
            GROUP BY bi.product_id, bi.product_name
            ORDER BY total_quantity DESC, bi.product_name ASC
            LIMIT 1
            """,
            tuple(date_params)
        )
        best_seller = cursor.fetchone()

        # Sales grouped by payment method for the selected dates.
        cursor.execute(
            f"""
            SELECT
                payment_method,
                COALESCE(SUM(final_amount), 0) AS payment_sales
            FROM bills
            WHERE {date_where}
            GROUP BY payment_method
            ORDER BY payment_method
            """,
            tuple(date_params)
        )
        payment_sales = cursor.fetchall()

        return render_template(
            "index.html",
            product_count=product_count,
            total_sales=sales_data["total_sales"],
            completed_bills=sales_data["completed_bills"],
            average_bill_value=sales_data["average_bill_value"],
            best_seller=best_seller,
            payment_sales=payment_sales,
            start_date=start_date,
            end_date=end_date
        )

    except Exception as error:
        print("Dashboard error:", repr(error))
        flash("Could not load dashboard data.", "error")

        return render_template(
            "index.html",
            product_count=0,
            total_sales=0,
            completed_bills=0,
            average_bill_value=0,
            best_seller=None,
            payment_sales=[],
            start_date=start_date,
            end_date=end_date
        )

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()





@app.route("/products")
def products():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        "SELECT product_id, product_name, unit_price, stock_quantity, is_active "
        "FROM products ORDER BY product_id"
    )

    product_list = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("products.html", products=product_list)

@app.route("/create-bill")
def create_bill():
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT product_id, product_name, unit_price, stock_quantity "
            "FROM products "
            "WHERE is_active = TRUE AND stock_quantity > 0 "
            "ORDER BY product_name"
        )

        product_list = cursor.fetchall()

        return render_template(
            "create_bill.html",
            products=product_list
        )

    except Exception as error:
        print("Create Bill error:", error)
        flash("Could not load products. Please check the terminal.", "error")
        return redirect(url_for("products"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

@app.route("/add-product", methods=["POST"])
def add_product():
    product_name = request.form.get("product_name", "").strip()
    unit_price_text = request.form.get("unit_price", "").strip()
    stock_quantity_text = request.form.get("stock_quantity", "").strip()

    if not product_name:
        flash("Product name is required.", "error")
        return redirect(url_for("products"))

    try:
        unit_price = float(unit_price_text)
        stock_quantity = int(stock_quantity_text)

        if unit_price <= 0 or stock_quantity < 0:
            flash("Invalid price or stock quantity.", "error")
            return redirect(url_for("products"))

    except (ValueError, TypeError):
        flash("Enter a valid price and stock quantity.", "error")
        return redirect(url_for("products"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT product_id FROM products WHERE LOWER(product_name) = LOWER(%s)",
            (product_name,)
        )

        existing_product = cursor.fetchone()

        # Consume any remaining rows before running another query.
        while cursor.fetchone() is not None:
            pass

        if existing_product:
            flash("This product already exists. Please use a different name.", "error")
        else:
            cursor.execute(
                "INSERT INTO products (product_name, unit_price, stock_quantity) "
                "VALUES (%s, %s, %s)",
                (product_name, unit_price, stock_quantity)
            )

            connection.commit()
            flash("Product added successfully!", "success")

    except Exception as error:
        if connection is not None:
            connection.rollback()

        print("Add product error:", error)
        flash("Could not add the product. Please check the terminal.", "error")

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(url_for("products"))

@app.route("/edit-product/<int:product_id>", methods=["POST"])
def edit_product(product_id):
    product_name = request.form.get("product_name", "").strip()
    unit_price_text = request.form.get("unit_price", "").strip()
    stock_quantity_text = request.form.get("stock_quantity", "").strip()

    if not product_name or len(product_name) > 100:
        flash("Enter a valid product name.", "error")
        return redirect(url_for("products"))

    try:
        unit_price = float(unit_price_text)
        stock_quantity = int(stock_quantity_text)

        if unit_price <= 0 or stock_quantity < 0:
            flash("Enter a valid price and stock quantity.", "error")
            return redirect(url_for("products"))

    except (ValueError, TypeError):
        flash("Enter valid product details.", "error")
        return redirect(url_for("products"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            "UPDATE products SET product_name = %s, unit_price = %s, stock_quantity = %s WHERE product_id = %s",
            (product_name, unit_price, stock_quantity, product_id)
        )

        connection.commit()

        if cursor.rowcount == 0:
            flash("Product not found or no changes were made.", "error")
        else:
            flash("Product updated successfully!", "success")

    except Exception as error:
        if connection is not None:
            connection.rollback()

        print("Edit product error:", error)
        flash("Could not update the product.", "error")

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(url_for("products"))


@app.route("/generate-bill", methods=["POST"])
def generate_bill():
    product_ids = request.form.getlist("product_id[]")
    quantities = request.form.getlist("quantity[]")
    discount_text = request.form.get("discount", "").strip()
    payment_method = request.form.get("payment_method", "").strip()

    # Validate the submitted product rows.
    if not product_ids or len(product_ids) != len(quantities):
        flash("Please select at least one product.", "error")
        return redirect(url_for("create_bill"))

    try:
        product_ids = [int(value) for value in product_ids]
        quantities = [int(value) for value in quantities]
        discount_percent = float(discount_text)

        if any(value <= 0 for value in product_ids):
            raise ValueError("Invalid product.")

        if any(value <= 0 for value in quantities):
            raise ValueError("Invalid quantity.")

        if len(set(product_ids)) != len(product_ids):
            flash("Each product can appear only once. Change its quantity instead.", "error")
            return redirect(url_for("create_bill"))

        if not 0 <= discount_percent <= 100:
            flash("Discount must be between 0 and 100.", "error")
            return redirect(url_for("create_bill"))

    except (ValueError, TypeError):
        flash("Please enter valid products, quantities, and discount.", "error")
        return redirect(url_for("create_bill"))

    if payment_method not in ["Cash", "UPI", "Card"]:
        flash("Please select a valid payment method.", "error")
        return redirect(url_for("create_bill"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        bill_items = []
        subtotal = 0.0

        # Lock and validate every selected product.
        for product_id, quantity in zip(product_ids, quantities):
            cursor.execute(
                """
                SELECT product_id, product_name, unit_price, stock_quantity
                FROM products
                WHERE product_id = %s AND is_active = TRUE
                FOR UPDATE
                """,
                (product_id,)
            )

            product = cursor.fetchone()

            if product is None:
                raise ValueError("A selected product was not found or is inactive.")

            if quantity > product["stock_quantity"]:
                raise ValueError(
                    f"Insufficient stock for {product['product_name']}."
                )

            unit_price = float(product["unit_price"])
            line_total = round(unit_price * quantity, 2)
            subtotal = round(subtotal + line_total, 2)

            bill_items.append({
                "product_id": product["product_id"],
                "product_name": product["product_name"],
                "unit_price": unit_price,
                "quantity": quantity,
                "line_total": line_total
            })

        discount_amount = round(subtotal * discount_percent / 100, 2)
        final_amount = round(subtotal - discount_amount, 2)

        # Insert the bill first to obtain its unique database ID.
        cursor.execute(
            """
            INSERT INTO bills (
                bill_number, subtotal, discount_percent, discount_amount,
                final_amount, payment_method, payment_status, bill_status, is_demo
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                "TEMP", subtotal, discount_percent, discount_amount,
                final_amount, payment_method, "Paid", "Completed", 0
            )
        )

        bill_id = cursor.lastrowid
        bill_number = f"RP-{bill_id:06d}"

        cursor.execute(
            "UPDATE bills SET bill_number = %s WHERE bill_id = %s",
            (bill_number, bill_id)
        )

        # Save each item and reduce its stock.
        for item in bill_items:
            cursor.execute(
                """
                INSERT INTO bill_items (
                    bill_id, product_id, product_name,
                    unit_price, quantity, line_total
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    bill_id,
                    item["product_id"],
                    item["product_name"],
                    item["unit_price"],
                    item["quantity"],
                    item["line_total"]
                )
            )

            cursor.execute(
                """
                UPDATE products
                SET stock_quantity = stock_quantity - %s
                WHERE product_id = %s AND stock_quantity >= %s
                """,
                (item["quantity"], item["product_id"], item["quantity"])
            )

            if cursor.rowcount != 1:
                raise RuntimeError("Stock update failed.")

        connection.commit()

        # Show the completed bill with every product.
        item_rows = "".join(
            f"""
            <tr>
                <td>{item['product_name']}</td>
                <td>{item['quantity']}</td>
                <td>₹{item['unit_price']:.2f}</td>
                <td>₹{item['line_total']:.2f}</td>
            </tr>
            """
            for item in bill_items
        )

        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bill Generated | RetailPro</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 700px;
                    margin: 30px auto;
                    padding: 20px;
                    background: #f4f6f9;
                }}
                .bill {{
                    background: white;
                    padding: 25px;
                    border-radius: 10px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 10px;
                    text-align: left;
                }}
                button, .link {{
                    display: inline-block;
                    padding: 12px 18px;
                    margin: 8px 5px 8px 0;
                    border: none;
                    border-radius: 5px;
                    background: #2563eb;
                    color: white;
                    text-decoration: none;
                    cursor: pointer;
                }}
                @media print {{
                    .no-print {{ display: none !important; }}
                    body {{ background: white; margin: 0; }}
                }}
            </style>
        </head>
        <body>
            <div class="bill">
                <h1>RetailPro</h1>
                <h2>Bill Generated Successfully!</h2>
                <hr>
                <p><strong>Bill Number:</strong> {bill_number}</p>

                <table>
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Quantity</th>
                            <th>Unit Price</th>
                            <th>Line Total</th>
                        </tr>
                    </thead>
                    <tbody>{item_rows}</tbody>
                </table>

                <p><strong>Subtotal:</strong> ₹{subtotal:.2f}</p>
                <p><strong>Discount ({discount_percent:.2f}%):</strong> ₹{discount_amount:.2f}</p>
                <h2>Final Amount: ₹{final_amount:.2f}</h2>
                <p><strong>Payment Method:</strong> {payment_method}</p>
                <p><strong>Payment Status:</strong> Paid</p>

                <div class="no-print">
                    <button type="button" onclick="window.print()">Print Bill</button>
                    <a class="link" href="/create-bill">Create Another Bill</a>
                    <a class="link" href="/transactions">View Transactions</a>
                </div>
            </div>
        </body>
        </html>
        """

    except ValueError as error:
        if connection is not None:
            connection.rollback()

        flash(str(error), "error")
        return redirect(url_for("create_bill"))

    except Exception as error:
        print("Generate bill error:", repr(error))

        if connection is not None:
            connection.rollback()

        flash("Could not generate the bill. Please try again.", "error")
        return redirect(url_for("create_bill"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()



@app.route("/bill-details/<int:bill_id>")
def bill_details(bill_id):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Get bill summary
        cursor.execute("""
            SELECT
                bill_id,
                bill_number,
                bill_date,
                subtotal,
                discount_percent,
                discount_amount,
                final_amount,
                payment_method,
                payment_status,
                bill_status
            FROM bills
            WHERE bill_id = %s
        """, (bill_id,))

        bill = cursor.fetchone()

        if bill is None:
            flash("Bill not found.", "error")
            return redirect(url_for("transactions"))

        # Get products included in this bill
        cursor.execute("""
            SELECT
                product_name,
                unit_price,
                quantity,
                line_total
            FROM bill_items
            WHERE bill_id = %s
            ORDER BY item_id
        """, (bill_id,))

        items = cursor.fetchall()

        return render_template(
            "bill_details.html",
            bill=bill,
            items=items
        )

    except Exception as error:
        print("Bill details error:", repr(error))
        flash("Could not load bill details.", "error")
        return redirect(url_for("transactions"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()



@app.route("/transactions")
def transactions():
    connection = None
    cursor = None

    try:
        bill_number = request.args.get("bill_number", "").strip()
        start_date = request.args.get("start_date", "").strip()
        end_date = request.args.get("end_date", "").strip()
        payment_status = request.args.get("payment_status", "").strip()

        query = """
            SELECT
                bill_id,
                bill_number,
                subtotal,
                discount_amount,
                final_amount,
                payment_method,
                payment_status,
                bill_status
            FROM bills
            WHERE 1=1
        """
        params = []

        if bill_number:
            query += " AND bill_number LIKE %s"
            params.append("%" + bill_number + "%")

        if start_date:
            query += " AND DATE(bill_date) >= %s"
            params.append(start_date)

        if end_date:
            query += " AND DATE(bill_date) <= %s"
            params.append(end_date)

        if payment_status:
            query += " AND payment_status = %s"
            params.append(payment_status)

        query += " ORDER BY bill_id DESC"

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, params)
        bill_list = cursor.fetchall()

        return render_template(
            "transactions.html",
            bills=bill_list
        )

    except Exception as error:
        print("Transactions error:", repr(error))
        flash("Could not load transaction history.", "error")
        return redirect(url_for("home"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()



@app.route("/deactivate-product/<int:product_id>", methods=["POST"])
def deactivate_product(product_id):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            "UPDATE products SET is_active = FALSE "
            "WHERE product_id = %s AND is_active = TRUE",
            (product_id,)
        )

        if cursor.rowcount == 1:
            connection.commit()
            flash("Product deactivated successfully!", "success")
        else:
            connection.rollback()
            flash("Product not found or already deactivated.", "error")

    except Exception as error:
        if connection is not None:
            connection.rollback()

        print("Deactivate product error:", repr(error))
        flash("Could not deactivate the product.", "error")

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(url_for("products"))



            
if __name__ == "__main__":
    app.run(debug=True)
            
