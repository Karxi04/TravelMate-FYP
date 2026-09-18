import 'models/budget_model.dart';


class BudgetService {


  BudgetModel calculateBudget({

    required double accommodation,
    required double food,
    required double transportation,
    required double activities,

  }) {


    return BudgetModel(
      accommodation: accommodation,
      food: food,
      transportation: transportation,
      activities: activities,
    );

  }



  List<Map<String,dynamic>> generateAlternatives(
      BudgetModel budget
      ) {


    List<Map<String,dynamic>> alternatives = [];


    if(budget.accommodation > 200){

      alternatives.add({

        "title":
        "Replace Accommodation",

        "description":
        "Change to lower cost hotel",

        "saving":
        150,

        "type":
        "hotel"

      });

    }



    if(budget.activities > 100){

      alternatives.add({

        "title":
        "Replace Activities",

        "description":
        "Choose free attractions",

        "saving":
        100,

        "type":
        "activity"

      });

    }



    if(budget.transportation > 100){

      alternatives.add({

        "title":
        "Use Public Transport",

        "description":
        "Replace private transport",

        "saving":
        80,

        "type":
        "transport"

      });

    }


    return alternatives;

  }

}