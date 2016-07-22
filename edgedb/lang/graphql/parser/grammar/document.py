##
# Copyright (c) 2016 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##


from edgedb.lang.common import parsing, context
from edgedb.lang.graphql import ast as gqlast
from edgedb.lang.graphql.parser.errors import (GraphQLParserError,
                                               GraphQLUniquenessError)

from .tokens import *
from . import keywords


def check_const(expr):
    if isinstance(expr, gqlast.Variable):
        raise GraphQLParserError.from_parsed(
            'unexpected variable, must be a constant value', expr)
    elif isinstance(expr, gqlast.ListLiteral):
        for val in expr.value:
            check_const(val)
    elif isinstance(expr, gqlast.ObjectLiteral):
        for field in expr.value:
            check_const(field.value)


class Nonterm(context.Nonterm):
    pass


class NameTokNontermMeta(context.ContextNontermMeta):
    def __new__(mcls, name, bases, dct, *, exceptions=tuple()):
        if name != 'NameTokNonTerm':
            prod = NameTokNonTerm._reduce_token

            tokens = ['IDENT']
            tokens.extend([
                tok for tok in
                keywords.by_type[keywords.UNRESERVED_KEYWORD].values()
                if tok not in exceptions])

            for tok in tokens:
                dct['reduce_' + tok] = prod

        cls = super().__new__(mcls, name, bases, dct)
        return cls

    def __init__(cls, name, bases, dct, *, exceptions=tuple()):
        super().__init__(name, bases, dct)


class NameTokNonTerm(Nonterm, metaclass=NameTokNontermMeta):
    def _reduce_token(self, kid):
        self.val = kid


class NameTok(NameTokNonTerm):
    pass


class NameNotONTok(NameTokNonTerm, exceptions=('ON',)):
    pass


class NameNotBoolTok(NameTokNonTerm, exceptions=('TRUE', 'FALSE')):
    pass


class BaseValue(Nonterm):
    def reduce_INTEGER(self, kid):
        self.val = gqlast.IntegerLiteral(value=kid.normalized_value)

    def reduce_FLOAT(self, kid):
        self.val = gqlast.FloatLiteral(value=kid.normalized_value)

    def reduce_TRUE(self, kid):
        self.val = gqlast.BooleanLiteral(value=True)

    def reduce_FALSE(self, kid):
        self.val = gqlast.BooleanLiteral(value=False)

    def reduce_STRING(self, kid):
        self.val = gqlast.StringLiteral(value=kid.normalized_value)

    def reduce_NameNotBoolTok(self, kid):
        if kid.val.val == 'null':
            raise GraphQLParserError.from_parsed(
                "'null' not allowed as value", kid.val)
        self.val = gqlast.EnumLiteral(value=kid.val.val)

    def reduce_LSBRACKET_RSBRACKET(self, *kids):
        self.val = gqlast.ListLiteral(value=[])

    def reduce_LSBRACKET_ValueList_RSBRACKET(self, *kids):
        self.val = gqlast.ListLiteral(value=kids[1].val)

    def reduce_LCBRACKET_RCBRACKET(self, *kids):
        self.val = gqlast.ObjectLiteral(value={})

    def reduce_LCBRACKET_ObjectFieldList_RCBRACKET(self, *kids):
        self.val = gqlast.ObjectLiteral(value=kids[1].val)


class Value(Nonterm):
    def reduce_BaseValue(self, kid):
        self.val = kid.val

    def reduce_VAR(self, kid):
        self.val = gqlast.Variable(value=kid.val)


class ValueList(parsing.ListNonterm, element=Value):
    pass


class ObjectField(Nonterm):
    def reduce_NameTok_COLON_Value(self, *kids):
        self.val = gqlast.ObjectField(name=kids[0].val.val, value=kids[2].val)


class ObjectFieldList(parsing.ListNonterm, element=ObjectField):
    pass


class OptValue(Nonterm):
    def reduce_BaseValue(self, kid):
        self.val = kid.val

    def reduce_empty(self):
        self.val = None


class OptNameTok(Nonterm):
    def reduce_NameTok(self, kid):
        self.val = kid.val

    def reduce_empty(self):
        self.val = None


class Document(Nonterm):
    "%start"

    def reduce_Definitions(self, kid):
        short = None
        fragnames = set()
        opnames = set()
        for defn in kid.val:
            if isinstance(defn, gqlast.OperationDefinition):
                if defn.name is not None:
                    if defn.name not in opnames:
                        opnames.add(defn.name)
                    else:
                        raise GraphQLUniquenessError.from_ast(defn,
                                                              'operation')

                elif (short is None and
                        defn.type is None and
                        not defn.variables and
                        not defn.directives):
                    short = defn
            elif isinstance(defn, gqlast.FragmentDefinition):
                if defn.name not in fragnames:
                    fragnames.add(defn.name)
                else:
                    raise GraphQLUniquenessError.from_ast(defn, 'fragment')

        if short is not None and len(kid.val) - len(fragnames) > 1:
            # we have more than one query definition, so short form is not
            # allowed
            #
            raise GraphQLParserError.from_parsed(
                'short form is not allowed here', short)

        self.val = gqlast.Document(definitions=kid.val)


class Definition(Nonterm):
    def reduce_Query(self, kid):
        self.val = kid.val

    def reduce_Fragment(self, kid):
        self.val = kid.val


class Definitions(parsing.ListNonterm, element=Definition):
    pass


class Query(Nonterm):
    def reduce_QueryTypeTok_OptNameTok_OptVariables_OptDirectives_SelectionSet(
            self, *kids):
        self.val = gqlast.OperationDefinition(
            type=kids[0].val.val,
            name=kids[1].val.val if kids[1].val else None,
            variables=kids[2].val,
            directives=kids[3].val,
            selection_set=kids[4].val)

    def reduce_SelectionSet(self, kid):
        self.val = gqlast.OperationDefinition(selection_set=kid.val)


class QueryTypeTok(Nonterm):
    def reduce_QUERY(self, kid):
        self.val = kid

    def reduce_MUTATION(self, kid):
        self.val = kid

    def reduce_SUBSCRIPTION(self, kid):
        self.val = kid


class Fragment(Nonterm):
    def reduce_FRAGMENT_NameNotONTok_TypeCondition_OptDirectives_SelectionSet(
            self, *kids):
        self.val = gqlast.FragmentDefinition(name=kids[1].val.val,
                                             on=kids[2].val,
                                             directives=kids[3].val,
                                             selection_set=kids[4].val)


class SelectionSet(Nonterm):
    def reduce_LCBRACKET_Selections_RCBRACKET(self, *kids):
        self.val = gqlast.SelectionSet(selections=kids[1].val)


class OptSelectionSet(Nonterm):
    def reduce_SelectionSet(self, kid):
        self.val = kid.val

    def reduce_empty(self):
        self.val = None


class Field(Nonterm):
    def reduce_AliasedField_OptArgs_OptDirectives_OptSelectionSet(self, *kids):
        self.val = kids[0].val
        self.val.arguments = kids[1].val
        self.val.directives = kids[2].val
        self.val.selection_set = kids[3].val


class AliasedField(Nonterm):
    def reduce_NameTok(self, kid):
        self.val = gqlast.Field(name=kid.val.val)

    def reduce_NameTok_COLON_NameTok(self, *kids):
        self.val = gqlast.Field(alias=kids[0].val.val, name=kids[2].val.val)


class FragmentSpread(Nonterm):
    def reduce_ELLIPSIS_NameNotONTok_OptDirectives(self, *kids):
        self.val = gqlast.FragmentSpread(name=kids[1].val.val,
                                         directives=kids[2].val)


class InlineFragment(Nonterm):
    def reduce_ELLIPSIS_OptTypeCondition_OptDirectives_SelectionSet(self,
                                                                    *kids):
        self.val = gqlast.InlineFragment(selection_set=kids[3].val,
                                         on=kids[1].val,
                                         directives=kids[2].val)


class Selection(Nonterm):
    def reduce_Field(self, kid):
        self.val = kid.val

    def reduce_FragmentSpread(self, kid):
        self.val = kid.val

    def reduce_InlineFragment(self, kid):
        self.val = kid.val


class Selections(parsing.ListNonterm, element=Selection):
    pass


class OptArgs(Nonterm):
    def reduce_Arguments(self, kid):
        self.val = kid.val

    def reduce_empty(self):
        self.val = []


class Arguments(Nonterm):
    def reduce_LPAREN_ArgumentList_RPAREN(self, *kids):
        self.val = kids[1].val
        # validate argument name uniqueness
        #
        argnames = set()
        for arg in self.val:
            if arg.name not in argnames:
                argnames.add(arg.name)
            else:
                raise GraphQLUniquenessError.from_ast(arg)


class Argument(Nonterm):
    def reduce_NameTok_COLON_Value(self, *kids):
        self.val = gqlast.Argument(name=kids[0].val.val, value=kids[2].val)


class ArgumentList(parsing.ListNonterm, element=Argument):
    pass


class OptDirectives(Nonterm):
    def reduce_Directives(self, kid):
        self.val = kid.val

    def reduce_empty(self):
        self.val = []


class Directive(Nonterm):
    def reduce_AT_NameTok_OptArgs(self, *kids):
        self.val = gqlast.Directive(name=kids[1].val.val,
                                    arguments=kids[2].val)


class Directives(parsing.ListNonterm, element=Directive):
    pass


class OptTypeCondition(Nonterm):
    def reduce_TypeCondition(self, kid):
        self.val = kid.val

    def reduce_empty(self):
        self.val = None


class TypeCondition(Nonterm):
    def reduce_ON_NameTok(self, *kids):
        self.val = kids[1].val.val


class OptVariables(Nonterm):
    def reduce_Variables(self, kid):
        self.val = kid.val

    def reduce_empty(self):
        self.val = None


class Variables(Nonterm):
    def reduce_LPAREN_VariableList_RPAREN(self, *kids):
        self.val = kids[1].val
        # validate argument name uniqueness
        #
        variables = set()
        for var in self.val:
            if var.name not in variables:
                variables.add(var.name)
            else:
                raise GraphQLUniquenessError.from_ast(var)


class Variable(Nonterm):
    def reduce_VAR_COLON_VarType_DefaultValue(self, *kids):
        self.val = gqlast.VariableDefinition(name=kids[0].val,
                                             type=kids[2].val,
                                             value=kids[3].val)


class VariableList(parsing.ListNonterm, element=Variable):
    pass


class VarType(Nonterm):
    def reduce_NameTok(self, kid):
        self.val = gqlast.VariableType(name=kid.val.val)

    def reduce_NameTok_BANG(self, kid):
        self.val = gqlast.VariableType(name=kid.val.val,
                                       nullable=False)

    def reduce_LSBRACKET_VarType_RSBRACKET(self, *kids):
        self.val = gqlast.VariableType(name=kids[1].val,
                                       list=True)

    def reduce_LSBRACKET_VarType_RSBRACKET_BANG(self, *kids):
        self.val = gqlast.VariableType(name=kids[1].val,
                                       list=True,
                                       nullable=False)


class DefaultValue(Nonterm):
    def reduce_EQUAL_BaseValue(self, *kids):
        check_const(kids[1].val)
        self.val = kids[1].val

    def reduce_empty(self):
        self.val = None